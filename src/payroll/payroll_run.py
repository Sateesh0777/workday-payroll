"""
payroll_run.py
Payroll Run Management.

Manages the lifecycle of payroll runs: scheduling, status tracking,
locking periods, and integrating with the PayrollProcessor for execution.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict

from src.payroll.payroll_processor import PayrollProcessor, PayrollRunSummary
from src.integrations.workday_api import WorkdayAPIClient

logger = logging.getLogger(__name__)


class PayrollRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    COMMITTED = "COMMITTED"
    VOIDED = "VOIDED"
    ERROR = "ERROR"


class PayrollRunType(str, Enum):
    REGULAR = "REGULAR"
    OFF_CYCLE = "OFF_CYCLE"
    SUPPLEMENTAL = "SUPPLEMENTAL"
    REVERSAL = "REVERSAL"


@dataclass
class PayrollRunRecord:
    run_id: str
    pay_group: str
    run_type: PayrollRunType
    pay_frequency: str
    period_start: date
    period_end: date
    pay_date: date
    status: PayrollRunStatus = PayrollRunStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    committed_at: Optional[datetime] = None
    error_message: str = ""
    summary: Optional[PayrollRunSummary] = None
    worker_ids: Optional[List[str]] = None

    def touch(self):
        self.updated_at = datetime.utcnow()


class PayrollRunManager:
    """
    Manages the full lifecycle of payroll runs.

    Usage::

        manager = PayrollRunManager(workday_client)
        record = manager.create_run(
            pay_group="BIWEEKLY-US",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 14),
            pay_date=date(2025, 1, 17),
        )
        record = manager.calculate(record.run_id)
        record = manager.approve(record.run_id, approved_by="manager@company.com")
        record = manager.commit(record.run_id)
    """

    def __init__(self, client: WorkdayAPIClient):
        self.client = client
        self.processor = PayrollProcessor(client)
        self._runs: Dict[str, PayrollRunRecord] = {}

    def create_run(
        self,
        pay_group: str,
        period_start: date,
        period_end: date,
        pay_date: date,
        run_type: PayrollRunType = PayrollRunType.REGULAR,
        pay_frequency: str = "BIWEEKLY",
        worker_ids: Optional[List[str]] = None,
    ) -> PayrollRunRecord:
        """Create a new payroll run in DRAFT status."""
        run_id = (
            f"PAY-{pay_group}-{period_start.strftime('%Y%m%d')}"
            f"-{uuid.uuid4().hex[:8].upper()}"
        )
        record = PayrollRunRecord(
            run_id=run_id,
            pay_group=pay_group,
            run_type=run_type,
            pay_frequency=pay_frequency,
            period_start=period_start,
            period_end=period_end,
            pay_date=pay_date,
            worker_ids=worker_ids,
        )
        self._runs[run_id] = record
        logger.info(
            "Created payroll run %s (%s) for %s -> %s",
            run_id, run_type.value, period_start, period_end,
        )
        return record

    def calculate(self, run_id: str) -> PayrollRunRecord:
        """Execute gross-to-net calculations for the run."""
        record = self._get_run(run_id)
        self._assert_status(record, [PayrollRunStatus.DRAFT, PayrollRunStatus.SCHEDULED])
        record.status = PayrollRunStatus.IN_PROGRESS
        record.touch()
        logger.info("Calculating payroll run %s", run_id)
        try:
            summary = self.processor.process_payroll_run(
                run_id=run_id,
                pay_group=record.pay_group,
                period_start=record.period_start,
                period_end=record.period_end,
                pay_date=record.pay_date,
                worker_ids=record.worker_ids,
            )
            record.summary = summary
            record.status = PayrollRunStatus.CALCULATED
            logger.info(
                "Run %s calculated: %d employees, gross=%s, net=%s, errors=%d",
                run_id, summary.employee_count, summary.total_gross,
                summary.total_net, len(summary.errors),
            )
        except Exception as exc:
            record.status = PayrollRunStatus.ERROR
            record.error_message = str(exc)
            logger.error("Run %s failed: %s", run_id, exc, exc_info=True)
        record.touch()
        return record

    def approve(self, run_id: str, approved_by: str) -> PayrollRunRecord:
        """Approve a calculated payroll run for payment."""
        record = self._get_run(run_id)
        self._assert_status(record, [PayrollRunStatus.CALCULATED])
        if record.summary and record.summary.errors:
            raise ValueError(
                f"Cannot approve run {run_id}: "
                f"{len(record.summary.errors)} employee errors must be resolved first."
            )
        record.status = PayrollRunStatus.APPROVED
        record.approved_by = approved_by
        record.approved_at = datetime.utcnow()
        record.touch()
        logger.info("Run %s approved by %s", run_id, approved_by)
        return record

    def commit(self, run_id: str) -> PayrollRunRecord:
        """Commit the payroll run and trigger payment processing."""
        record = self._get_run(run_id)
        self._assert_status(record, [PayrollRunStatus.APPROVED])
        logger.info("Committing payroll run %s", run_id)
        # In production: self.client.submit_payroll_results(run_id, record.summary)
        record.status = PayrollRunStatus.COMMITTED
        record.committed_at = datetime.utcnow()
        record.touch()
        logger.info("Run %s committed successfully", run_id)
        return record

    def void_run(self, run_id: str, reason: str) -> PayrollRunRecord:
        """Void a run that has not yet been committed."""
        record = self._get_run(run_id)
        voidable = [
            PayrollRunStatus.DRAFT,
            PayrollRunStatus.SCHEDULED,
            PayrollRunStatus.CALCULATED,
            PayrollRunStatus.APPROVED,
            PayrollRunStatus.ERROR,
        ]
        self._assert_status(record, voidable)
        record.status = PayrollRunStatus.VOIDED
        record.error_message = f"Voided: {reason}"
        record.touch()
        logger.info("Run %s voided. Reason: %s", run_id, reason)
        return record

    def get_run(self, run_id: str) -> Optional[PayrollRunRecord]:
        return self._runs.get(run_id)

    def list_runs(
        self,
        pay_group: Optional[str] = None,
        status: Optional[PayrollRunStatus] = None,
    ) -> List[PayrollRunRecord]:
        runs = list(self._runs.values())
        if pay_group:
            runs = [r for r in runs if r.pay_group == pay_group]
        if status:
            runs = [r for r in runs if r.status == status]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)

    def _get_run(self, run_id: str) -> PayrollRunRecord:
        record = self._runs.get(run_id)
        if not record:
            raise KeyError(f"Payroll run '{run_id}' not found.")
        return record

    def _assert_status(
        self, record: PayrollRunRecord, allowed: List[PayrollRunStatus]
    ):
        if record.status not in allowed:
            allowed_str = ", ".join(s.value for s in allowed)
            raise ValueError(
                f"Run {record.run_id} is in status '{record.status.value}'. "
                f"Expected one of: {allowed_str}."
            )


def generate_biweekly_schedule(
    pay_group: str,
    year: int,
    first_period_start: date,
    pay_lag_days: int = 3,
) -> List[PayrollRunRecord]:
    """Generate all 26 biweekly payroll run records for a given year."""
    records = []
    period_start = first_period_start
    while period_start.year <= year:
        period_end = period_start + timedelta(days=13)
        pay_date = period_end + timedelta(days=pay_lag_days)
        run_id = f"PAY-{pay_group}-{period_start.strftime('%Y%m%d')}"
        record = PayrollRunRecord(
            run_id=run_id,
            pay_group=pay_group,
            run_type=PayrollRunType.REGULAR,
            pay_frequency="BIWEEKLY",
            period_start=period_start,
            period_end=period_end,
            pay_date=pay_date,
            status=PayrollRunStatus.SCHEDULED,
        )
        records.append(record)
        period_start = period_end + timedelta(days=1)
    return records
