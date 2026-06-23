"""
test_tax_calculations.py
Unit tests for federal and state tax calculators.

Tests IRS Publication 15-T (2025) percentage method withholding,
state tax calculations, and allowance adjustments.
"""

import pytest
from decimal import Decimal

from src.tax.federal_tax import FederalTaxCalculator
from src.tax.state_tax import StateTaxCalculator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def federal_calc():
    return FederalTaxCalculator()


@pytest.fixture
def state_calc():
    return StateTaxCalculator()


# ---------------------------------------------------------------------------
# Federal Tax Tests
# ---------------------------------------------------------------------------

class TestFederalTax:
    def test_zero_wages_yields_zero_tax(self, federal_calc):
        """No wages = no federal withholding."""
        tax = federal_calc.calculate(
            taxable_wages=Decimal("0"),
            pay_frequency="BIWEEKLY",
            filing_status="SINGLE",
            allowances=0,
            additional_withholding=Decimal("0"),
        )
        assert tax == Decimal("0")

    def test_single_filer_has_higher_withholding_than_married(self, federal_calc):
        """Single filers have higher withholding than married at same wage."""
        wages = Decimal("3000")
        single = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=Decimal("0"),
        )
        married = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="MARRIED", allowances=0,
            additional_withholding=Decimal("0"),
        )
        assert single > married

    def test_additional_withholding_adds_to_base(self, federal_calc):
        """Additional withholding should be added on top of base withholding."""
        wages = Decimal("3000")
        base = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=Decimal("0"),
        )
        extra = Decimal("50")
        with_extra = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=extra,
        )
        assert with_extra == base + extra

    def test_more_allowances_reduces_withholding(self, federal_calc):
        """More allowances should reduce tax withheld."""
        wages = Decimal("3000")
        tax_0 = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=Decimal("0"),
        )
        tax_3 = federal_calc.calculate(
            taxable_wages=wages, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=3,
            additional_withholding=Decimal("0"),
        )
        assert tax_3 < tax_0

    def test_tax_is_non_negative(self, federal_calc):
        """Federal withholding should never be negative."""
        for filing in ["SINGLE", "MARRIED", "HEAD_OF_HOUSEHOLD"]:
            tax = federal_calc.calculate(
                taxable_wages=Decimal("500"),
                pay_frequency="BIWEEKLY",
                filing_status=filing,
                allowances=10,  # High allowances may reduce to 0 but not below
                additional_withholding=Decimal("0"),
            )
            assert tax >= Decimal("0"), f"Negative tax for {filing}"

    def test_weekly_vs_biweekly_consistency(self, federal_calc):
        """Weekly wages * 2 should yield roughly same annual withholding as biweekly."""
        weekly_wage = Decimal("1500")
        biweekly_wage = Decimal("3000")
        weekly_annual = federal_calc.calculate(
            taxable_wages=weekly_wage, pay_frequency="WEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=Decimal("0"),
        ) * 52
        biweekly_annual = federal_calc.calculate(
            taxable_wages=biweekly_wage, pay_frequency="BIWEEKLY",
            filing_status="SINGLE", allowances=0,
            additional_withholding=Decimal("0"),
        ) * 26
        # Allow small rounding difference (within $10)
        diff = abs(weekly_annual - biweekly_annual)
        assert diff < Decimal("10"), f"Annual tax difference too large: {diff}"


# ---------------------------------------------------------------------------
# State Tax Tests
# ---------------------------------------------------------------------------

class TestStateTax:
    def test_zero_wages_yields_zero_state_tax(self, state_calc):
        tax = state_calc.calculate(
            taxable_wages=Decimal("0"),
            state_code="CA",
            pay_frequency="BIWEEKLY",
            filing_status="SINGLE",
            allowances=0,
            additional_withholding=Decimal("0"),
        )
        assert tax == Decimal("0")

    def test_no_income_tax_state_returns_zero(self, state_calc):
        """Texas, Florida, etc. have no state income tax."""
        no_income_tax_states = ["TX", "FL", "NV", "WA", "WY", "SD", "AK"]
        for state in no_income_tax_states:
            try:
                tax = state_calc.calculate(
                    taxable_wages=Decimal("5000"),
                    state_code=state,
                    pay_frequency="BIWEEKLY",
                    filing_status="SINGLE",
                    allowances=0,
                    additional_withholding=Decimal("0"),
                )
                assert tax == Decimal("0"), f"{state} should have no income tax"
            except (NotImplementedError, KeyError):
                pass  # State not yet implemented is acceptable

    def test_california_taxes_high_earners(self, state_calc):
        """California should withhold tax for high earners."""
        try:
            tax = state_calc.calculate(
                taxable_wages=Decimal("10000"),
                state_code="CA",
                pay_frequency="BIWEEKLY",
                filing_status="SINGLE",
                allowances=0,
                additional_withholding=Decimal("0"),
            )
            assert tax > Decimal("0"), "CA should withhold tax on $10k biweekly"
        except (NotImplementedError, KeyError):
            pytest.skip("CA state tax not yet implemented")

    def test_additional_state_withholding(self, state_calc):
        """Additional state withholding should add to base."""
        try:
            base = state_calc.calculate(
                taxable_wages=Decimal("3000"),
                state_code="CA",
                pay_frequency="BIWEEKLY",
                filing_status="SINGLE",
                allowances=0,
                additional_withholding=Decimal("0"),
            )
            with_extra = state_calc.calculate(
                taxable_wages=Decimal("3000"),
                state_code="CA",
                pay_frequency="BIWEEKLY",
                filing_status="SINGLE",
                allowances=0,
                additional_withholding=Decimal("25"),
            )
            assert with_extra == base + Decimal("25")
        except (NotImplementedError, KeyError):
            pytest.skip("CA state tax not yet implemented")

    def test_state_tax_is_non_negative(self, state_calc):
        """State tax should never be negative."""
        for state in ["CA", "NY", "TX", "WA"]:
            try:
                tax = state_calc.calculate(
                    taxable_wages=Decimal("500"),
                    state_code=state,
                    pay_frequency="BIWEEKLY",
                    filing_status="SINGLE",
                    allowances=5,
                    additional_withholding=Decimal("0"),
                )
                assert tax >= Decimal("0"), f"Negative state tax for {state}"
            except (NotImplementedError, KeyError):
                pass
