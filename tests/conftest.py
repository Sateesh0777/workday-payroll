"""
conftest.py
Shared pytest fixtures for the workday-payroll test suite.

These fixtures are automatically available to all test files.
"""

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from src.payroll.payroll_processor import (
    PayrollProcessor,
    EmployeePayrollInput,
    PayrollRunSummary,
)
from src.payroll.compensation_calculator import PayPeriod
from src.deductions.benefits_deduction import BenefitsDeductionCalculator
from src.deductions.retirement_deduction import RetirementDeductionCalculator
from src.deductions.garnishment import GarnishmentCalculator
from src.tax.federal_tax import FederalTaxCalculator
from src.tax.state_tax import StateTaxCalculator


# ---------------------------------------------------------------------------
# Shared mock clients
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mock_workday_client():
    """Session-scoped mock WorkdayAPIClient."""
    client = MagicMock()
    client.get_all_workers.return_value = []
    return client


# ---------------------------------------------------------------------------
# Calculator fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def processor(mock_workday_client):
    """PayrollProcessor with mocked API client."""
    return PayrollProcessor(mock_workday_client)


@pytest.fixture
def federal_calc():
    """FederalTaxCalculator instance."""
    return FederalTaxCalculator()


@pytest.fixture
def state_calc():
    """StateTaxCalculator instance."""
    return StateTaxCalculator()


@pytest.fixture
def benefits_calc():
    """BenefitsDeductionCalculator instance."""
    return BenefitsDeductionCalculator()


@pytest.fixture
def retirement_calc():
    """RetirementDeductionCalculator instance."""
    return RetirementDeductionCalculator()


@pytest.fixture
def garnishment_calc():
    """GarnishmentCalculator instance."""
    return GarnishmentCalculator()


# ---------------------------------------------------------------------------
# Pay period fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def biweekly_period():
    """Standard biweekly pay period for Jan 1-14 2025."""
    return PayPeriod(
        frequency="BIWEEKLY",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 14),
    )


@pytest.fixture
def period_start():
    return date(2025, 1, 1)


@pytest.fixture
def period_end():
    return date(2025, 1, 14)


@pytest.fixture
def pay_date():
    return date(2025, 1, 17)


# ---------------------------------------------------------------------------
# Employee input fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def salaried_employee_input():
    """Minimal salaried EmployeePayrollInput for biweekly $78k."""
    return EmployeePayrollInput(
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


@pytest.fixture
def hourly_employee_input():
    """Hourly employee at $25/hr with 8 OT hours."""
    return EmployeePayrollInput(
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


# ---------------------------------------------------------------------------
# Benefit election helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def medical_election():
    """Simple medical benefit election dict."""
    return {
        "benefitType": "MEDICAL",
        "planName": "Blue Shield PPO",
        "employeePremium": 250.0,
        "employerPremium": 500.0,
        "ytdEmployee": 0,
    }


@pytest.fixture
def retirement_election_6pct():
    """6% 401(k) pre-tax election dict."""
    return {
        "planType": "401K",
        "contributionType": "PRETAX",
        "electionType": "PERCENTAGE",
        "electionAmount": 0.06,
        "ytdEmployee": 0,
    }
