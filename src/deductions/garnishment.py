"""
garnishment.py
Wage Garnishment Processing.

Handles court-ordered wage garnishments including child support, tax levies,
student loan garnishments, and creditor garnishments. Enforces federal and
state disposable earnings limits (CCPA Title III).
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional, Dict

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Garnishment types and priority ordering (per federal rules)
# ---------------------------------------------------------------------------

class GarnishmentType(str, Enum):
    """Types of wage garnishment, ordered by federal priority."""
    CHILD_SUPPORT = "CHILD_SUPPORT"           # Highest priority
    ALIMONY = "ALIMONY"
    TAX_LEVY_FEDERAL = "TAX_LEVY_FEDERAL"     # IRS tax levy
    TAX_LEVY_STATE = "TAX_LEVY_STATE"
    STUDENT_LOAN = "STUDENT_LOAN"
    CREDITOR = "CREDITOR"                     # Lowest priority
    BANKRUPTCY = "BANKRUPTCY"


# CCPA Title III: Maximum percentage of disposable earnings that can be garnished
# For standard creditor garnishments
CCPA_DISPOSABLE_LIMITS: Dict[str, Decimal] = {
    "CREDITOR":        Decimal("0.25"),    # 25% of disposable earnings OR
    "STUDENT_LOAN":    Decimal("0.15"),    # 15% for student loans
    "BANKRUPTCY":      Decimal("0.25"),
    # Child support limits depend on whether employee supports another family
    "CHILD_SUPPORT_NO_OTHER":   Decimal("0.60"),  # 60% (no other family)
    "CHILD_SUPPORT_OTHER":      Decimal("0.50"),  # 50% (supporting another family)
    "CHILD_SUPPORT_ARREARS_NO_OTHER": Decimal("0.65"),  # 12+ weeks arrears
    "CHILD_SUPPORT_ARREARS_OTHER":    Decimal("0.55"),
}

# Federal minimum wage for CCPA 30x threshold (2025)
FEDERAL_MINIMUM_WAGE = Decimal("7.25")
CCPA_PROTECTED_EARNINGS = FEDERAL_MINIMUM_WAGE * 30  # $217.50/week


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class GarnishmentOrder:
    """Represents a single court-ordered garnishment."""
    order_id: str
    garnishment_type: GarnishmentType
    creditor_name: str
    # Amount to withhold per period (fixed) OR None if percentage-based
    fixed_amount: Optional[Decimal] = None
    # Percentage of disposable earnings (0.0 to 1.0), if not fixed
    percentage: Optional[Decimal] = None
    # Maximum total obligation (None = no cap)
    total_obligation: Optional[Decimal] = None
    # Amount already collected (for tracking against total_obligation)
    amount_collected: Decimal = Decimal("0")
    # Whether employee is 12+ weeks in arrears (child support only)
    in_arrears: bool = False
    # Whether employee supports another family (child support only)
    supports_other_family: bool = False
    # State-specific rules may override federal limits
    state_code: str = "FED"
    is_active: bool = True

    @property
    def remaining_obligation(self) -> Optional[Decimal]:
        if self.total_obligation is None:
            return None
        return max(Decimal("0"), self.total_obligation - self.amount_collected)


@dataclass
class GarnishmentResult:
    """Result of garnishment calculation for one pay period."""
    total_garnishment: Decimal = Decimal("0")
    line_items: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    # Disposable earnings used for limit calculations
    disposable_earnings: Decimal = Decimal("0")
    # Maximum that could be garnished under CCPA
    ccpa_maximum: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class GarnishmentCalculator:
    """
    Wage Garnishment Calculator (CCPA Title III compliant).

    Calculates garnishment amounts respecting:
    - Federal CCPA disposable earnings limits
    - Priority ordering when multiple garnishments exist
    - Remaining obligation caps
    - State law overrides (where more restrictive than federal)

    Usage::

        calc = GarnishmentCalculator()
        result = calc.calculate(
            orders=employee.garnishment_orders,
            gross_pay=Decimal("3000.00"),
            pretax_deductions=Decimal("200.00"),   # 401k, benefits
            federal_tax=Decimal("400.00"),
            state_tax=Decimal("150.00"),
            fica=Decimal("229.50"),
            pay_frequency="BIWEEKLY",
        )
        total_garnishment = result.total_garnishment
    """

    def calculate(
        self,
        orders: List[GarnishmentOrder],
        gross_pay: Decimal,
        pretax_deductions: Decimal,
        federal_tax: Decimal,
        state_tax: Decimal,
        fica: Decimal,
        pay_frequency: str = "BIWEEKLY",
    ) -> GarnishmentResult:
        """
        Calculate total garnishment for a pay period.

        Args:
            orders:             Active garnishment orders for the employee.
            gross_pay:          Gross earnings for the period.
            pretax_deductions:  Pre-tax benefit/retirement deductions.
            federal_tax:        Federal income tax withheld.
            state_tax:          State income tax withheld.
            fica:               FICA taxes (SS + Medicare).
            pay_frequency:      Pay frequency for CCPA 30x threshold scaling.

        Returns:
            GarnishmentResult with per-order line items and CCPA validation.
        """
        result = GarnishmentResult()
        active_orders = [o for o in orders if o.is_active]
        if not active_orders:
            return result

        # Disposable earnings = gross - mandatory deductions (NOT voluntary)
        mandatory_deductions = federal_tax + state_tax + fica
        disposable = _round(gross_pay - mandatory_deductions)
        result.disposable_earnings = disposable

        # CCPA 30x minimum wage protection (scaled to pay period)
        protected = self._ccpa_protected(pay_frequency)

        # Maximum garnishable = disposable - protected (for creditor garnishments)
        ccpa_max_creditor = max(Decimal("0"), min(
            _round(disposable * CCPA_DISPOSABLE_LIMITS["CREDITOR"]),
            _round(disposable - protected),
        ))
        result.ccpa_maximum = ccpa_max_creditor

        # Sort orders by priority
        priority_order = [
            GarnishmentType.CHILD_SUPPORT,
            GarnishmentType.ALIMONY,
            GarnishmentType.TAX_LEVY_FEDERAL,
            GarnishmentType.TAX_LEVY_STATE,
            GarnishmentType.STUDENT_LOAN,
            GarnishmentType.CREDITOR,
            GarnishmentType.BANKRUPTCY,
        ]
        sorted_orders = sorted(
            active_orders,
            key=lambda o: priority_order.index(o.garnishment_type)
            if o.garnishment_type in priority_order else 99,
        )

        remaining_disposable = disposable

        for order in sorted_orders:
            if remaining_disposable <= 0:
                break

            # Calculate gross amount for this order
            if order.fixed_amount is not None:
                gross_amount = order.fixed_amount
            elif order.percentage is not None:
                gross_amount = _round(disposable * order.percentage)
            else:
                result.warnings.append(
                    f"Order {order.order_id}: no fixed_amount or percentage set. Skipping."
                )
                continue

            # Cap at remaining obligation
            if order.remaining_obligation is not None:
                gross_amount = min(gross_amount, order.remaining_obligation)

            # Apply CCPA limits based on garnishment type
            ccpa_limit = self._ccpa_limit(order, disposable, protected)
            gross_amount = min(gross_amount, ccpa_limit)

            # Ensure we don't over-garnish remaining disposable
            actual_amount = min(gross_amount, remaining_disposable)
            actual_amount = _round(actual_amount)

            if actual_amount <= 0:
                result.warnings.append(
                    f"Order {order.order_id}: disposable earnings exhausted or CCPA limit reached."
                )
                continue

            remaining_disposable -= actual_amount
            result.total_garnishment += actual_amount

            result.line_items.append({
                "orderId": order.order_id,
                "garnishmentType": order.garnishment_type.value,
                "creditorName": order.creditor_name,
                "amount": actual_amount,
                "disposableEarnings": disposable,
                "ccpaLimit": ccpa_limit,
            })

        result.total_garnishment = _round(result.total_garnishment)
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ccpa_protected(self, pay_frequency: str) -> Decimal:
        """Return the CCPA 30x minimum-wage protection scaled to pay frequency."""
        multipliers = {
            "WEEKLY": Decimal("1"),
            "BIWEEKLY": Decimal("2"),
            "SEMIMONTHLY": Decimal("2.167"),
            "MONTHLY": Decimal("4.333"),
        }
        factor = multipliers.get(pay_frequency.upper(), Decimal("2"))
        return _round(CCPA_PROTECTED_EARNINGS * factor)

    def _ccpa_limit(
        self,
        order: GarnishmentOrder,
        disposable: Decimal,
        protected: Decimal,
    ) -> Decimal:
        """Return the maximum garnishable amount for this order type."""
        gtype = order.garnishment_type

        if gtype in (GarnishmentType.CHILD_SUPPORT, GarnishmentType.ALIMONY):
            if order.in_arrears:
                pct_key = (
                    "CHILD_SUPPORT_ARREARS_OTHER"
                    if order.supports_other_family
                    else "CHILD_SUPPORT_ARREARS_NO_OTHER"
                )
            else:
                pct_key = (
                    "CHILD_SUPPORT_OTHER"
                    if order.supports_other_family
                    else "CHILD_SUPPORT_NO_OTHER"
                )
            pct = CCPA_DISPOSABLE_LIMITS[pct_key]
            return _round(disposable * pct)

        if gtype in (GarnishmentType.TAX_LEVY_FEDERAL, GarnishmentType.TAX_LEVY_STATE):
            # IRS/state tax levies have their own exempt amount tables;
            # apply no CCPA percentage cap (handled by levy calculation separately).
            return disposable

        if gtype == GarnishmentType.STUDENT_LOAN:
            pct = CCPA_DISPOSABLE_LIMITS["STUDENT_LOAN"]
            return min(
                _round(disposable * pct),
                max(Decimal("0"), disposable - protected),
            )

        # Creditor / Bankruptcy
        pct = CCPA_DISPOSABLE_LIMITS.get(gtype.value, CCPA_DISPOSABLE_LIMITS["CREDITOR"])
        return min(
            _round(disposable * pct),
            max(Decimal("0"), disposable - protected),
        )

    def calculate_from_dicts(
        self,
        garnishment_dicts: List[Dict],
        gross_pay: Decimal,
        pretax_deductions: Decimal,
        federal_tax: Decimal,
        state_tax: Decimal,
        fica: Decimal,
        pay_frequency: str = "BIWEEKLY",
    ) -> GarnishmentResult:
        """Dict-based interface for Workday API payloads."""
        orders = []
        for g in garnishment_dicts:
            gtype = GarnishmentType(g.get("garnishmentType", "CREDITOR"))
            orders.append(GarnishmentOrder(
                order_id=g.get("orderId", ""),
                garnishment_type=gtype,
                creditor_name=g.get("creditorName", ""),
                fixed_amount=(
                    Decimal(str(g["amount"])) if "amount" in g else None
                ),
                percentage=(
                    Decimal(str(g["percentage"])) if "percentage" in g else None
                ),
                total_obligation=(
                    Decimal(str(g["totalObligation"])) if "totalObligation" in g else None
                ),
                amount_collected=Decimal(str(g.get("amountCollected", 0))),
                in_arrears=g.get("inArrears", False),
                supports_other_family=g.get("supportsOtherFamily", False),
                state_code=g.get("stateCode", "FED"),
                is_active=g.get("isActive", True),
            ))
        return self.calculate(
            orders=orders,
            gross_pay=gross_pay,
            pretax_deductions=pretax_deductions,
            federal_tax=federal_tax,
            state_tax=state_tax,
            fica=fica,
            pay_frequency=pay_frequency,
        )
