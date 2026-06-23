"""
test_deductions.py
Unit tests for benefits and retirement deduction calculators.

Tests pre-tax/post-tax benefit deductions, IRS limits enforcement,
401(k) calculations, employer matching, and garnishment processing.
"""

import pytest
from decimal import Decimal

from src.deductions.benefits_deduction import (
    BenefitsDeductionCalculator,
    BenefitElection,
)
from src.deductions.retirement_deduction import (
    RetirementDeductionCalculator,
)
from src.deductions.garnishment import (
    GarnishmentCalculator,
    GarnishmentOrder,
    GarnishmentType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def benefits_calc():
    return BenefitsDeductionCalculator()


@pytest.fixture
def retirement_calc():
    return RetirementDeductionCalculator()


@pytest.fixture
def garnishment_calc():
    return GarnishmentCalculator()


# ---------------------------------------------------------------------------
# Benefits Deduction Tests
# ---------------------------------------------------------------------------

class TestBenefitsDeduction:
    def test_empty_elections_returns_zero(self, benefits_calc):
        result = benefits_calc.calculate([])
        assert result.pretax_total == Decimal("0")
        assert result.posttax_total == Decimal("0")
        assert result.employer_contribution == Decimal("0")

    def test_medical_is_pretax(self, benefits_calc):
        elections = [{
            "benefitType": "MEDICAL",
            "planName": "Blue Shield PPO",
            "employeePremium": 250.0,
            "employerPremium": 500.0,
            "ytdEmployee": 0,
        }]
        result = benefits_calc.calculate(elections)
        assert result.pretax_total == Decimal("250.00")
        assert result.posttax_total == Decimal("0")
        assert result.employer_contribution == Decimal("500.00")

    def test_supplemental_life_is_posttax(self, benefits_calc):
        elections = [{
            "benefitType": "SUPPLEMENTAL_LIFE",
            "planName": "Supplemental Life",
            "employeePremium": 15.0,
            "employerPremium": 0.0,
            "ytdEmployee": 0,
        }]
        result = benefits_calc.calculate(elections)
        assert result.posttax_total == Decimal("15.00")
        assert result.pretax_total == Decimal("0")

    def test_multiple_benefit_types_aggregated(self, benefits_calc):
        elections = [
            {"benefitType": "MEDICAL", "employeePremium": 200.0, "employerPremium": 400.0, "ytdEmployee": 0},
            {"benefitType": "DENTAL", "employeePremium": 20.0, "employerPremium": 30.0, "ytdEmployee": 0},
            {"benefitType": "SUPPLEMENTAL_LIFE", "employeePremium": 10.0, "employerPremium": 0.0, "ytdEmployee": 0},
        ]
        result = benefits_calc.calculate(elections)
        assert result.pretax_total == Decimal("220.00")
        assert result.posttax_total == Decimal("10.00")
        assert result.employer_contribution == Decimal("430.00")

    def test_fsa_annual_limit_enforced(self, benefits_calc):
        """FSA election should not exceed 2025 IRS limit of $3,300."""
        elections = [{
            "benefitType": "FSA_HEALTH",
            "employeePremium": 500.0,  # Way over monthly limit
            "employerPremium": 0.0,
            "annualLimit": 3300.0,
            "ytdEmployee": 3200.0,  # Only $100 remaining
        }]
        result = benefits_calc.calculate(elections)
        # Should be capped at $100 (remaining)
        assert result.pretax_total <= Decimal("100.00")

    def test_imputed_income_no_excess(self, benefits_calc):
        """No imputed income if employer life <= $50k."""
        imputed = benefits_calc.imputed_income(
            employer_life_face_value=Decimal("50000"),
            employee_age=45,
        )
        assert imputed == Decimal("0")

    def test_imputed_income_with_excess(self, benefits_calc):
        """Imputed income calculated for coverage over $50k."""
        imputed = benefits_calc.imputed_income(
            employer_life_face_value=Decimal("100000"),
            employee_age=45,
        )
        assert imputed > Decimal("0")


# ---------------------------------------------------------------------------
# Retirement Deduction Tests
# ---------------------------------------------------------------------------

class TestRetirementDeduction:
    def test_empty_elections_returns_zero(self, retirement_calc):
        result = retirement_calc.calculate([], Decimal("3000"))
        assert result.pretax_401k == Decimal("0")
        assert result.roth_401k == Decimal("0")

    def test_percentage_based_401k(self, retirement_calc):
        elections = [{
            "planType": "401K",
            "contributionType": "PRETAX",
            "electionType": "PERCENTAGE",
            "electionAmount": 0.06,  # 6%
            "ytdEmployee": 0,
        }]
        result = retirement_calc.calculate(elections, Decimal("3000"))
        expected = Decimal("3000") * Decimal("0.06")
        assert abs(result.pretax_401k - expected) <= Decimal("0.02")

    def test_fixed_amount_401k(self, retirement_calc):
        elections = [{
            "planType": "401K",
            "contributionType": "PRETAX",
            "electionType": "FIXED",
            "electionAmount": 200.0,
            "ytdEmployee": 0,
        }]
        result = retirement_calc.calculate(elections, Decimal("3000"))
        assert result.pretax_401k == Decimal("200.00")

    def test_annual_limit_capped(self, retirement_calc):
        """401k should not exceed $23,500 annual limit (2025)."""
        elections = [{
            "planType": "401K",
            "contributionType": "PRETAX",
            "electionType": "FIXED",
            "electionAmount": 5000.0,  # Would exceed limit if allowed
            "ytdEmployee": 23400.0,    # Only $100 remaining
        }]
        result = retirement_calc.calculate(elections, Decimal("10000"))
        assert result.pretax_401k <= Decimal("100.00")


# ---------------------------------------------------------------------------
# Garnishment Tests
# ---------------------------------------------------------------------------

class TestGarnishment:
    def test_no_orders_returns_zero(self, garnishment_calc):
        result = garnishment_calc.calculate(
            orders=[],
            gross_pay=Decimal("3000"),
            pretax_deductions=Decimal("200"),
            federal_tax=Decimal("400"),
            state_tax=Decimal("150"),
            fica=Decimal("229.50"),
        )
        assert result.total_garnishment == Decimal("0")

    def test_creditor_garnishment_capped_at_ccpa(self, garnishment_calc):
        """Creditor garnishment capped at 25% of disposable or above 30x min wage."""
        order = GarnishmentOrder(
            order_id="GARN-001",
            garnishment_type=GarnishmentType.CREDITOR,
            creditor_name="First Bank",
            fixed_amount=Decimal("5000"),  # Very high amount - should be capped
        )
        result = garnishment_calc.calculate(
            orders=[order],
            gross_pay=Decimal("3000"),
            pretax_deductions=Decimal("0"),
            federal_tax=Decimal("300"),
            state_tax=Decimal("100"),
            fica=Decimal("229.50"),
        )
        # Should be capped by CCPA - not full $5000
        assert result.total_garnishment < Decimal("5000")
        assert result.total_garnishment >= Decimal("0")

    def test_child_support_higher_limit_than_creditor(self, garnishment_calc):
        """Child support can garnish up to 60% vs 25% for creditors."""
        gross = Decimal("3000")
        taxes = Decimal("629.50")
        disposable = gross - taxes

        cs_order = GarnishmentOrder(
            order_id="CS-001",
            garnishment_type=GarnishmentType.CHILD_SUPPORT,
            creditor_name="State Child Support",
            fixed_amount=Decimal("2000"),
            supports_other_family=False,
        )
        cred_order = GarnishmentOrder(
            order_id="CRED-001",
            garnishment_type=GarnishmentType.CREDITOR,
            creditor_name="Creditor",
            fixed_amount=Decimal("2000"),
        )

        cs_result = garnishment_calc.calculate(
            orders=[cs_order],
            gross_pay=gross, pretax_deductions=Decimal("0"),
            federal_tax=Decimal("300"), state_tax=Decimal("100"),
            fica=Decimal("229.50"),
        )
        cred_result = garnishment_calc.calculate(
            orders=[cred_order],
            gross_pay=gross, pretax_deductions=Decimal("0"),
            federal_tax=Decimal("300"), state_tax=Decimal("100"),
            fica=Decimal("229.50"),
        )
        # Child support should allow more garnishment
        assert cs_result.total_garnishment >= cred_result.total_garnishment

    def test_inactive_order_ignored(self, garnishment_calc):
        order = GarnishmentOrder(
            order_id="GARN-INACTIVE",
            garnishment_type=GarnishmentType.CREDITOR,
            creditor_name="Old Debt",
            fixed_amount=Decimal("500"),
            is_active=False,
        )
        result = garnishment_calc.calculate(
            orders=[order],
            gross_pay=Decimal("3000"),
            pretax_deductions=Decimal("0"),
            federal_tax=Decimal("300"),
            state_tax=Decimal("100"),
            fica=Decimal("229.50"),
        )
        assert result.total_garnishment == Decimal("0")
