"""
time_tracking.py
Time & Attendance Integration.

Syncs employee hours from Workday Time Tracking into the payroll system.
Handles regular hours, overtime, shift differentials, and absence hours.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Dict

from src.integrations.workday_api import WorkdayAPIClient, WorkdayAPIError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TimeEntry:
    """A single time entry record for an employee."""
    worker_id: str
    entry_date: date
    hours: Decimal
    time_type: str            # REGULAR | OVERTIME | DOUBLE_TIME | HOLIDAY | PTO | SICK
    shift_code: Optional[str] = None  # e.g. "NIGHT", "WEEKEND"
    shift_differential: Decimal = Decimal("0")  # Additional hourly premium
    approved: bool = False
    entry_id: str = ""


@dataclass
class WorkerTimeSummary:
    """Aggregated time data for one worker over a pay period."""
    worker_id: str
    period_start: date
    period_end: date
    regular_hours: Decimal = Decimal("0")
    overtime_hours: Decimal = Decimal("0")
    double_time_hours: Decimal = Decimal("0")
    holiday_hours: Decimal = Decimal("0")
    pto_hours: Decimal = Decimal("0")
    sick_hours: Decimal = Decimal("0")
    shift_differential: Decimal = Decimal("0")
    entries: List[TimeEntry] = field(default_factory=list)

    @property
    def total_hours(self) -> Decimal:
        return (
            self.regular_hours + self.overtime_hours + self.double_time_hours
            + self.holiday_hours + self.pto_hours + self.sick_hours
        )


# ---------------------------------------------------------------------------
# Time Tracking Integration
# ---------------------------------------------------------------------------

class TimeTrackingIntegration:
    """
    Integrates Workday Time Tracking data with payroll processing.

    Fetches approved time entries from Workday, validates them,
    and produces WorkerTimeSummary objects used by the payroll engine.

    Usage::

        tracker = TimeTrackingIntegration(workday_client)
        summaries = tracker.get_period_summaries(
            pay_group="BIWEEKLY-US",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 14),
        )
        for summary in summaries:
            print(f"{summary.worker_id}: {summary.regular_hours}h regular, "
                  f"{summary.overtime_hours}h OT")
    """

    # Hours per week threshold for automatic OT detection (federal standard)
    WEEKLY_OT_THRESHOLD = Decimal("40")

    def __init__(self, client: WorkdayAPIClient):
        self.client = client

    def get_period_summaries(
        self,
        pay_group: str,
        period_start: date,
        period_end: date,
        worker_ids: Optional[List[str]] = None,
        require_approved: bool = True,
    ) -> List[WorkerTimeSummary]:
        """
        Fetch and aggregate time entries for all workers in a pay period.

        Args:
            pay_group:        Pay group to retrieve workers for.
            period_start:     Start of the pay period.
            period_end:       End of the pay period.
            worker_ids:       Optional subset of workers.
            require_approved: Only include approved time entries.

        Returns:
            List of WorkerTimeSummary objects ready for payroll calculation.
        """
        # Fetch raw time entries from Workday API
        raw_entries = self._fetch_time_entries(
            pay_group, period_start, period_end, worker_ids, require_approved
        )

        # Group entries by worker
        workers: Dict[str, List[TimeEntry]] = {}
        for entry in raw_entries:
            workers.setdefault(entry.worker_id, []).append(entry)

        summaries = []
        for wid, entries in workers.items():
            summary = self._aggregate_entries(wid, entries, period_start, period_end)
            summaries.append(summary)

        logger.info(
            "Time tracking: %d workers processed for %s -> %s",
            len(summaries), period_start, period_end,
        )
        return summaries

    def get_worker_summary(
        self,
        worker_id: str,
        period_start: date,
        period_end: date,
        require_approved: bool = True,
    ) -> WorkerTimeSummary:
        """Fetch time summary for a single worker."""
        try:
            raw = self.client.get_worker_time_entries(
                worker_id=worker_id,
                start_date=str(period_start),
                end_date=str(period_end),
            )
        except WorkdayAPIError as e:
            logger.warning("Could not fetch time for worker %s: %s", worker_id, e)
            raw = []

        entries = [
            self._map_entry(worker_id, r)
            for r in raw
            if not require_approved or r.get("status") == "APPROVED"
        ]
        return self._aggregate_entries(worker_id, entries, period_start, period_end)

    # ------------------------------------------------------------------
    # Private methods
    # ------------------------------------------------------------------

    def _fetch_time_entries(
        self,
        pay_group: str,
        period_start: date,
        period_end: date,
        worker_ids: Optional[List[str]],
        require_approved: bool,
    ) -> List[TimeEntry]:
        """Fetch raw time entries from Workday for all workers in pay group."""
        entries = []
        try:
            workers = self.client.get_all_workers(as_of_date=str(period_end))
            if worker_ids:
                workers = [w for w in workers if w.get("workerId") in worker_ids]

            for worker in workers:
                wid = worker.get("workerId")
                try:
                    raw = self.client.get_worker_time_entries(
                        worker_id=wid,
                        start_date=str(period_start),
                        end_date=str(period_end),
                    )
                    for r in raw:
                        if require_approved and r.get("status") != "APPROVED":
                            continue
                        entries.append(self._map_entry(wid, r))
                except WorkdayAPIError as e:
                    logger.warning("Time fetch failed for worker %s: %s", wid, e)
        except WorkdayAPIError as e:
            logger.error("Failed to fetch workers for time tracking: %s", e)

        return entries

    def _map_entry(self, worker_id: str, raw: Dict) -> TimeEntry:
        """Map a raw Workday time entry dict to a TimeEntry dataclass."""
        entry_date_str = raw.get("date", "")
        try:
            entry_date = date.fromisoformat(entry_date_str)
        except (ValueError, TypeError):
            entry_date = date.today()

        return TimeEntry(
            worker_id=worker_id,
            entry_id=raw.get("timeEntryId", ""),
            entry_date=entry_date,
            hours=Decimal(str(raw.get("hours", 0))),
            time_type=raw.get("timeType", "REGULAR").upper(),
            shift_code=raw.get("shiftCode"),
            shift_differential=Decimal(str(raw.get("shiftDifferential", 0))),
            approved=raw.get("status") == "APPROVED",
        )

    def _aggregate_entries(
        self,
        worker_id: str,
        entries: List[TimeEntry],
        period_start: date,
        period_end: date,
    ) -> WorkerTimeSummary:
        """Aggregate time entries into a WorkerTimeSummary."""
        summary = WorkerTimeSummary(
            worker_id=worker_id,
            period_start=period_start,
            period_end=period_end,
            entries=entries,
        )

        for entry in entries:
            ttype = entry.time_type
            if ttype == "REGULAR":
                summary.regular_hours += entry.hours
            elif ttype == "OVERTIME":
                summary.overtime_hours += entry.hours
            elif ttype == "DOUBLE_TIME":
                summary.double_time_hours += entry.hours
            elif ttype == "HOLIDAY":
                summary.holiday_hours += entry.hours
            elif ttype == "PTO":
                summary.pto_hours += entry.hours
            elif ttype == "SICK":
                summary.sick_hours += entry.hours
            else:
                summary.regular_hours += entry.hours

            # Use the highest shift differential seen in the period
            if entry.shift_differential > summary.shift_differential:
                summary.shift_differential = entry.shift_differential

        return summary

    def auto_detect_overtime(
        self,
        summary: WorkerTimeSummary,
    ) -> WorkerTimeSummary:
        """
        Auto-detect overtime from total hours if not already classified.
        Moves hours beyond 40/week threshold from regular to overtime.
        Operates week-by-week within the period.
        """
        if summary.overtime_hours > 0:
            # Overtime already classified by Workday
            return summary

        # Group entries by week
        weeks: Dict[int, Decimal] = {}
        for entry in summary.entries:
            week_num = (entry.entry_date - summary.period_start).days // 7
            weeks[week_num] = weeks.get(week_num, Decimal("0")) + (
                entry.hours if entry.time_type == "REGULAR" else Decimal("0")
            )

        total_ot = Decimal("0")
        for week_hours in weeks.values():
            ot = max(Decimal("0"), week_hours - self.WEEKLY_OT_THRESHOLD)
            total_ot += ot

        summary.regular_hours -= total_ot
        summary.overtime_hours += total_ot
        return summary
