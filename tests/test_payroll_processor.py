"""
test_payroll_processor.py
Unit tests for the PayrollProcessor engine.

Tests the full gross-to-net payroll calculation pipeline including
gross pay, FICA, federal/state taxes, deductions, and net pay.
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.payroll.payroll_processor import (
    PayrollProcessor,
    EmployeePayrollInput,
    EmployeePayrollResult,
    PayrollRunSummary,
)
from src.payroll.compensation_calculator import PayPeriod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_workday_client():
    """Return a mock WorkdayAPIClient."""
    client = MagicMock()
    client.get_all_workers.return_value = []
    return client


@pytest.fixture
def processor(mock_workday_client):
    """Return a PayrollProcessor with a mocked API client."""
    return PayrollProcessor(mock_workday_client)


@pytest.fixture
def biweekly_period():
    return PayPeriod(
        frequency="BIWEEKLY",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 14),
    )


def make_salaried_employee(**overrides) -> EmployeePayrollInput:
    """Return a minimal salaried EmployeePayrollInput for testing."""
    defaults = dict(
        worker_id="W001",
        full_name="Alice Smith",
        pay_group="BIWEEKLY-US",
        pay_frequency="BIWEEKLY",
        annual_salary=Decimal("78000"),
        hourly_rate=Decimal("0"),
        hours_worked=Decimal("80"),
        overtime_hours=Decimal("0"),
        bonus_amount=Decimal("0"),
        commission_amount=Decimal("0"),
        filing_status="SINGLE",
        federal_allowances=0,
        state_code="CA",
        state_allowances=0,
        additional_federal_withholding=Decimal("0"),
        additional_state_withholding=Decimal("0"),
        benefits_elections=[],
        retirement_elections=[],
        garnishments=[],
        ytd_gross=Decimal("0"),
        ytd_federal_tax=Decimal("0"),
        ytd_state_tax=Decimal("0"),
        ytd_social_security=Decimal("0"),
        ytd_medicare=Decimal("0"),
    )
    defaults.update(overrides)
    return EmployeePayrollInput(**defaults)


def make_hourly_employee(**overrides) -> EmployeePayrollInput:
    defaults = dict(
        worker_id="W002",
        full_name="Bob Jones",
        pay_group="BIWEEKLY-US",
        pay_frequency="BIWEEKLY",
        annual_salary=Decimal("0"),
        hourly_rate=Decimal("25.00"),
        hours_worked=Decimal("88"),
        overtime_hours=Decimal("8"),
        bonus_amount=Decimal("0"),
        commission_amount=Decimal("0"),
        filing_status="MARRIED",
        federal_allowances=2,
        state_code="TX",
        state_allowances=0,
        additional_federal_withholding=Decimal("0"),
        additional_state_withholding=Decimal("0"),
        benefits_elections=[],
        retirement_elections=[],
        garnishments=[],
        ytd_gross=Decimal("0"),
        ytd_federal_tax=Decimal("0"),
        ytd_state_tax=Decimal("0"),
        ytd_social_security=Decimal("0"),
        ytd_medicare=Decimal("0"),
    )
    defaults.update(overrides)
    return EmployeePayrollInput(**defaults)


# ---------------------------------------------------------------------------
# Tests: Gross pay
# ---------------------------------------------------------------------------

class TestGrossPay:
    def test_salaried_regular_pay(self, processor):
        """Salaried gross pay = annual / 26 for biweekly."""
        emp = make_salaried_employee(annual_salary=Decimal("78000"))
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        expected_regular = Decimal("3000.00")  # 78000 / 26
        assert result.regular_pay == expected_regular

    def test_hourly_regular_and_ot(self, processor):
        """Hourly employee: regular = 80h * rate, OT = 8h * rate * 1.5."""
        emp = make_hourly_employee(
            hourly_rate=Decimal("20.00"),
            hours_worked=Decimal("88"),
            overtime_hours=Decimal("8"),
        )
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        expected_regular = Decimal("1600.00")  # 80 * 20
        expected_ot = Decimal("240.00")         # 8 * 20 * 1.5
        assert result.regular_pay == expected_regular
        assert result.overtime_pay == expected_ot

    def test_bonus_included_in_gross(self, processor):
        emp = make_salaried_employee(bonus_amount=Decimal("500"))
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        assert result.bonus_pay == Decimal("500.00")
        assert result.gross_pay == result.regular_pay + Decimal("500.00")


# ---------------------------------------------------------------------------
# Tests: FICA
# ---------------------------------------------------------------------------

class TestFICA:
    def test_social_security_rate(self, processor):
        """SS tax = 6.2% of wages (up to wage base)."""
        wages = Decimal("3000.00")
        ss, _ = processor._calculate_social_security(wages, ytd_gross=Decimal("0"))
        expected = (wages * Decimal("0.062")).quantize(Decimal("0.01"))
        assert ss == expected

    def test_social_security_wage_base_cap(self, processor):
        """SS tax should be capped at the annual wage base."""
        wages = Decimal("5000.00")
        # Simulate YTD already at wage base
        ytd = processor.SOCIAL_SECURITY_WAGE_BASE
        ss, employer_ss = processor._calculate_social_security(wages, ytd_gross=ytd)
        assert ss == Decimal("0.00")
        assert employer_ss == Decimal("0.00")

    def test_medicare_rate(self, processor):
        """Medicare = 1.45% of wages."""
        wages = Decimal("3000.00")
        med, _ = processor._calculate_medicare(wages, ytd_gross=Decimal("0"))
        expected = (wages * Decimal("0.0145")).quantize(Decimal("0.01"))
        assert med == expected

    def test_additional_medicare_above_threshold(self, processor):
        """Additional 0.9% Medicare for wages over $200k."""
        wages = Decimal("5000.00")
        ytd = Decimal("198000.00")  # 198k + 5k = 203k > 200k
        med, _ = processor._calculate_medicare(wages, ytd_gross=ytd)
        base_med = (wages * Decimal("0.0145")).quantize(Decimal("0.01"))
        excess = Decimal("203000") - Decimal("200000")
        excess = min(excess, wages)
        additional = (excess * Decimal("0.009")).quantize(Decimal("0.01"))
        assert med == base_med + additional


# ---------------------------------------------------------------------------
# Tests: Net pay
# ---------------------------------------------------------------------------

class TestNetPay:
    def test_net_pay_is_gross_minus_deductions(self, processor):
        """net_pay = gross_pay - total_deductions."""
        emp = make_salaried_employee()
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        assert result.net_pay == result.gross_pay - result.total_deductions

    def test_net_pay_positive(self, processor):
        """Net pay should be non-negative for normal employees."""
        emp = make_salaried_employee()
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        assert result.net_pay >= Decimal("0")

    def test_total_deductions_include_taxes(self, processor):
        emp = make_salaried_employee()
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        # total_taxes should be a subset of total_deductions
        assert result.total_taxes <= result.total_deductions


# ---------------------------------------------------------------------------
# Tests: Payroll run
# ---------------------------------------------------------------------------

class TestPayrollRun:
    def test_empty_run_returns_zero_totals(self, processor, mock_workday_client):
        """A payroll run with no workers should return zeroed summary."""
        mock_workday_client.get_all_workers.return_value = []
        summary = processor.process_payroll_run(
            run_id="TEST-001",
            pay_group="BIWEEKLY-US",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 14),
            pay_date=date(2025, 1, 17),
        )
        assert summary.employee_count == 0
        assert summary.total_gross == Decimal("0")
        assert summary.total_net == Decimal("0")
        assert summary.errors == []

    def test_run_summary_has_correct_run_id(self, processor, mock_workday_client):
        mock_workday_client.get_all_workers.return_value = []
        summary = processor.process_payroll_run(
            run_id="RUN-XYZ",
            pay_group="BIWEEKLY-US",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 14),
            pay_date=date(2025, 1, 17),
        )
        assert summary.run_id == "RUN-XYZ"

    def test_line_items_built_for_employee(self, processor):
        """Line items should include at minimum a regular pay entry."""
        emp = make_salaried_employee()
        result = processor._calculate_employee_payroll(
            emp, date(2025, 1, 1), date(2025, 1, 14), date(2025, 1, 17)
        )
        codes = [li.code for li in result.line_items]
        assert "REG" in codes
