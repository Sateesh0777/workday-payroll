"""
direct_deposit.py
Direct Deposit / Payment Distribution Integration.

Manages employee bank account information and generates ACH payment
instructions for direct deposit. Supports split deposits across
multiple accounts (checking, savings, remainder).
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AccountType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"


class DepositType(str, Enum):
    FIXED_AMOUNT = "FIXED_AMOUNT"   # Deposit a specific dollar amount
    PERCENTAGE = "PERCENTAGE"       # Deposit a percentage of net pay
    REMAINDER = "REMAINDER"         # Deposit whatever is left (must be last)


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class BankAccount:
    """Employee bank account for direct deposit."""
    account_id: str
    worker_id: str
    bank_name: str
    routing_number: str        # ABA 9-digit routing number
    account_number: str        # Masked in logs/display
    account_type: AccountType
    deposit_type: DepositType
    priority: int              # 1 = first processed; remainder must be highest number
    # For FIXED_AMOUNT: dollar amount. For PERCENTAGE: 0.0-1.0. For REMAINDER: ignored.
    amount_or_pct: Decimal = Decimal("0")
    is_active: bool = True
    prenote_status: str = "APPROVED"  # PENDING | APPROVED | REJECTED

    @property
    def masked_account(self) -> str:
        """Return account number with all but last 4 digits masked."""
        if len(self.account_number) <= 4:
            return self.account_number
        return "****" + self.account_number[-4:]


@dataclass
class PaymentInstruction:
    """A single ACH payment instruction for one employee/account."""
    worker_id: str
    full_name: str
    bank_name: str
    routing_number: str
    account_number: str
    account_type: AccountType
    amount: Decimal
    payment_date: str           # ISO date string
    trace_number: str = ""
    status: PaymentStatus = PaymentStatus.PENDING
    payroll_run_id: str = ""


@dataclass
class DirectDepositResult:
    """Result of distributing net pay across an employee's accounts."""
    worker_id: str
    net_pay: Decimal
    instructions: List[PaymentInstruction] = field(default_factory=list)
    unallocated: Decimal = Decimal("0")
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Direct Deposit Calculator / Distributor
# ---------------------------------------------------------------------------

class DirectDepositManager:
    """
    Manages direct deposit distribution and ACH file generation.

    Distributes net pay across employee bank accounts according to
    split deposit elections, validates allocations, and produces
    payment instructions ready for ACH submission.

    Usage::

        manager = DirectDepositManager()
        result = manager.distribute(
            worker_id="W001",
            full_name="Jane Smith",
            net_pay=Decimal("2500.00"),
            accounts=employee_bank_accounts,
            payment_date="2025-01-17",
            payroll_run_id="PAY-001",
        )
        total_allocated = sum(i.amount for i in result.instructions)
    """

    def distribute(
        self,
        worker_id: str,
        full_name: str,
        net_pay: Decimal,
        accounts: List[BankAccount],
        payment_date: str,
        payroll_run_id: str = "",
    ) -> DirectDepositResult:
        """
        Distribute net pay across employee bank accounts.

        Priority order:
          1. FIXED_AMOUNT accounts (sorted by priority asc)
          2. PERCENTAGE accounts (sorted by priority asc)
          3. REMAINDER account (should be exactly one)

        Args:
            worker_id:      Workday worker ID.
            full_name:      Employee full name.
            net_pay:        Net pay amount to distribute.
            accounts:       Employee bank account elections.
            payment_date:   Payment date (ISO format).
            payroll_run_id: Payroll run reference.

        Returns:
            DirectDepositResult with payment instructions.
        """
        result = DirectDepositResult(worker_id=worker_id, net_pay=net_pay)
        active = [a for a in accounts if a.is_active and a.prenote_status == "APPROVED"]

        if not active:
            result.warnings.append(
                f"Worker {worker_id}: no active, approved direct deposit accounts. "
                "Payment will be issued as a paper check."
            )
            result.unallocated = net_pay
            return result

        # Sort: fixed first, then percentage, then remainder — within each group by priority
        fixed = sorted([a for a in active if a.deposit_type == DepositType.FIXED_AMOUNT], key=lambda x: x.priority)
        pct = sorted([a for a in active if a.deposit_type == DepositType.PERCENTAGE], key=lambda x: x.priority)
        remainder_accts = [a for a in active if a.deposit_type == DepositType.REMAINDER]

        if len(remainder_accts) > 1:
            result.warnings.append(
                f"Worker {worker_id}: {len(remainder_accts)} REMAINDER accounts found. "
                "Only the lowest-priority one will receive the remainder."
            )
            remainder_accts = [sorted(remainder_accts, key=lambda x: x.priority)[-1]]

        remaining = net_pay

        # 1. Fixed amount accounts
        for acct in fixed:
            amount = min(_round(acct.amount_or_pct), remaining)
            if amount <= 0:
                result.warnings.append(
                    f"Worker {worker_id}: insufficient net pay for fixed deposit "
                    f"to {acct.bank_name} ({acct.masked_account}). Skipping."
                )
                continue
            result.instructions.append(self._make_instruction(
                worker_id, full_name, acct, amount, payment_date, payroll_run_id
            ))
            remaining -= amount

        # 2. Percentage accounts
        for acct in pct:
            amount = min(_round(net_pay * acct.amount_or_pct), remaining)
            if amount <= 0:
                result.warnings.append(
                    f"Worker {worker_id}: no remaining pay for percentage deposit "
                    f"to {acct.bank_name} ({acct.masked_account})."
                )
                continue
            result.instructions.append(self._make_instruction(
                worker_id, full_name, acct, amount, payment_date, payroll_run_id
            ))
            remaining -= amount

        # 3. Remainder account
        if remainder_accts and remaining > 0:
            acct = remainder_accts[0]
            result.instructions.append(self._make_instruction(
                worker_id, full_name, acct, remaining, payment_date, payroll_run_id
            ))
            remaining = Decimal("0")

        result.unallocated = _round(remaining)
        if result.unallocated > 0:
            result.warnings.append(
                f"Worker {worker_id}: {result.unallocated} unallocated "
                "(no REMAINDER account). Will issue as paper check."
            )

        return result

    def generate_ach_batch(
        self,
        results: List[DirectDepositResult],
        company_name: str,
        company_id: str,
        effective_date: str,
    ) -> List[Dict]:
        """
        Generate ACH batch entries from a list of DirectDepositResults.

        Returns a list of dicts representing ACH 6-record (entry detail) fields,
        ready for formatting into a NACHA file.
        """
        batch_entries = []
        trace_seq = 1

        for result in results:
            for instr in result.instructions:
                trace_number = f"{company_id[-8:]}{trace_seq:07d}"
                instr.trace_number = trace_number
                instr.status = PaymentStatus.SUBMITTED
                batch_entries.append({
                    "recordType": "6",
                    "transactionCode": "22" if instr.account_type == AccountType.CHECKING else "32",
                    "routingNumber": instr.routing_number,
                    "accountNumber": instr.account_number,
                    "amount": str(instr.amount),
                    "individualId": instr.worker_id,
                    "individualName": instr.full_name[:22],
                    "traceNumber": trace_number,
                    "effectiveDate": effective_date,
                    "companyName": company_name[:16],
                    "companyId": company_id,
                })
                trace_seq += 1

        logger.info(
            "Generated ACH batch with %d entries totalling %s",
            len(batch_entries),
            sum(Decimal(e["amount"]) for e in batch_entries),
        )
        return batch_entries

    @staticmethod
    def _make_instruction(
        worker_id: str,
        full_name: str,
        acct: BankAccount,
        amount: Decimal,
        payment_date: str,
        payroll_run_id: str,
    ) -> PaymentInstruction:
        return PaymentInstruction(
            worker_id=worker_id,
            full_name=full_name,
            bank_name=acct.bank_name,
            routing_number=acct.routing_number,
            account_number=acct.account_number,
            account_type=acct.account_type,
            amount=amount,
            payment_date=payment_date,
            payroll_run_id=payroll_run_id,
        )

    def distribute_from_dicts(
        self,
        worker_id: str,
        full_name: str,
        net_pay: Decimal,
        account_dicts: List[Dict],
        payment_date: str,
        payroll_run_id: str = "",
    ) -> DirectDepositResult:
        """Dict-based interface for Workday API payloads."""
        accounts = []
        for d in account_dicts:
            accounts.append(BankAccount(
                account_id=d.get("accountId", ""),
                worker_id=worker_id,
                bank_name=d.get("bankName", ""),
                routing_number=d.get("routingNumber", ""),
                account_number=d.get("accountNumber", ""),
                account_type=AccountType(d.get("accountType", "CHECKING")),
                deposit_type=DepositType(d.get("depositType", "REMAINDER")),
                priority=int(d.get("priority", 99)),
                amount_or_pct=Decimal(str(d.get("amountOrPct", 0))),
                is_active=d.get("isActive", True),
                prenote_status=d.get("prenoteStatus", "APPROVED"),
            ))
        return self.distribute(
            worker_id=worker_id,
            full_name=full_name,
            net_pay=net_pay,
            accounts=accounts,
            payment_date=payment_date,
            payroll_run_id=payroll_run_id,
        )
