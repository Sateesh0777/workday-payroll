"""
federal_tax.py
Federal Income Tax Withholding Calculator.

Implements IRS Publication 15-T (2025) Percentage Method Tables for
automated payroll systems. Supports both pre-2020 and 2020+ W-4 forms.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 2025 Standard Withholding Allowance (per allowance per period)
# IRS Publication 15-T Table 1
# ---------------------------------------------------------------------------
ALLOWANCE_PER_PERIOD: Dict[str, Decimal] = {
    "WEEKLY":       Decimal("100.00"),
    "BIWEEKLY":     Decimal("200.00"),
    "SEMIMONTHLY":  Decimal("216.67"),
    "MONTHLY":      Decimal("433.33"),
}

# ---------------------------------------------------------------------------
# 2025 Standard Deduction Amounts (used with 2020+ W-4)
# IRS Publication 15-T Table 2
# ---------------------------------------------------------------------------
STANDARD_DEDUCTION_2020: Dict[str, Dict[str, Decimal]] = {
    "SINGLE": {
        "WEEKLY":       Decimal("299.04"),
        "BIWEEKLY":     Decimal("598.08"),
        "SEMIMONTHLY":  Decimal("647.92"),
        "MONTHLY":      Decimal("1295.83"),
    },
    "MARRIED": {
        "WEEKLY":       Decimal("598.08"),
        "BIWEEKLY":     Decimal("1196.15"),
        "SEMIMONTHLY":  Decimal("1295.83"),
        "MONTHLY":      Decimal("2591.67"),
    },
    "HEAD_OF_HOUSEHOLD": {
        "WEEKLY":       Decimal("447.12"),
        "BIWEEKLY":     Decimal("894.23"),
        "SEMIMONTHLY":  Decimal("968.75"),
        "MONTHLY":      Decimal("1937.50"),
    },
}

# ---------------------------------------------------------------------------
# 2025 Percentage Method Tax Brackets
# Format: (bracket_floor, rate, base_tax_at_floor)
# Amounts are ANNUAL. We annualize wages before applying, then de-annualize.
# IRS Publication 15-T Table 2 (Annual payroll period)
# ---------------------------------------------------------------------------
TAX_BRACKETS_ANNUAL: Dict[str, List[Tuple[Decimal, Decimal, Decimal]]] = {
    "SINGLE": [
        (Decimal("0"),       Decimal("0.10"), Decimal("0")),
        (Decimal("11925"),   Decimal("0.12"), Decimal("1192.50")),
        (Decimal("48475"),   Decimal("0.22"), Decimal("5578.50")),
        (Decimal("103350"),  Decimal("0.24"), Decimal("17651.00")),
        (Decimal("197300"),  Decimal("0.32"), Decimal("40199.00")),
        (Decimal("250525"),  Decimal("0.35"), Decimal("57231.00")),
        (Decimal("626350"),  Decimal("0.37"), Decimal("188769.75")),
    ],
    "MARRIED": [
        (Decimal("0"),       Decimal("0.10"), Decimal("0")),
        (Decimal("23850"),   Decimal("0.12"), Decimal("2385.00")),
        (Decimal("96950"),   Decimal("0.22"), Decimal("11157.00")),
        (Decimal("206700"),  Decimal("0.24"), Decimal("35302.00")),
        (Decimal("394600"),  Decimal("0.32"), Decimal("80398.00")),
        (Decimal("501050"),  Decimal("0.35"), Decimal("114462.00")),
        (Decimal("751600"),  Decimal("0.37"), Decimal("202154.50")),
    ],
    "HEAD_OF_HOUSEHOLD": [
        (Decimal("0"),       Decimal("0.10"), Decimal("0")),
        (Decimal("17000"),   Decimal("0.12"), Decimal("1700.00")),
        (Decimal("64850"),   Decimal("0.22"), Decimal("7442.00")),
        (Decimal("103350"),  Decimal("0.24"), Decimal("15912.00")),
        (Decimal("197300"),  Decimal("0.32"), Decimal("38460.00")),
        (Decimal("250500"),  Decimal("0.35"), Decimal("55484.00")),
        (Decimal("626350"),  Decimal("0.37"), Decimal("187031.50")),
    ],
}


class FederalTaxCalculator:
    """
    IRS Percentage Method Federal Income Tax Withholding Calculator (2025).

    Supports:
    - Pre-2020 W-4 (allowances-based)
    - 2020+ W-4 (standard deduction method)
    - Additional flat withholding
    - All filing statuses: SINGLE, MARRIED, HEAD_OF_HOUSEHOLD

    Usage:
        calc = FederalTaxCalculator()
        tax = calc.calculate(
            taxable_wages=Decimal("3000.00"),
            pay_frequency="BIWEEKLY",
            filing_status="SINGLE",
            allowances=1,
        )
    """

    def calculate(
        self,
        taxable_wages: Decimal,
        pay_frequency: str,
        filing_status: str,
        allowances: int = 0,
        additional_withholding: Decimal = Decimal("0"),
        use_2020_w4: bool = True,
        other_income_annual: Decimal = Decimal("0"),
        deductions_annual: Decimal = Decimal("0"),
        extra_withholding_annual: Decimal = Decimal("0"),
    ) -> Decimal:
        """
        Calculate federal income tax withholding for a single pay period.

        Args:
            taxable_wages:            Pre-tax gross wages after pre-tax deductions.
            pay_frequency:            WEEKLY | BIWEEKLY | SEMIMONTHLY | MONTHLY.
            filing_status:            SINGLE | MARRIED | HEAD_OF_HOUSEHOLD.
            allowances:               Number of allowances (pre-2020 W-4).
            additional_withholding:   Flat additional amount to withhold.
            use_2020_w4:              If True, use 2020+ standard deduction method.
            other_income_annual:      Step 4a on 2020+ W-4 (annualized).
            deductions_annual:        Step 4b on 2020+ W-4 (annualized deductions).
            extra_withholding_annual: Step 4c on 2020+ W-4 annualized equivalent.

        Returns:
            Federal income tax withholding amount for the period (rounded).
        """
        freq = pay_frequency.upper()
        status = filing_status.upper()
        periods = self._periods_per_year(freq)

        if use_2020_w4:
            tax = self._calculate_2020_w4(
                taxable_wages, freq, status, periods,
                other_income_annual, deductions_annual, extra_withholding_annual
            )
        else:
            tax = self._calculate_pre2020_w4(taxable_wages, freq, status, periods, allowances)

        tax = max(Decimal("0"), tax + additional_withholding)
        return _round(tax)

    def _calculate_2020_w4(
        self,
        wages: Decimal,
        freq: str,
        status: str,
        periods: int,
        other_income_annual: Decimal,
        deductions_annual: Decimal,
        extra_withholding_annual: Decimal,
    ) -> Decimal:
        """2020+ W-4 Percentage Method (Publication 15-T, Worksheet 1)."""
        # Step 1: Annualize wages
        annual_wages = wages * Decimal(str(periods))

        # Step 2: Add Step 4a (other income)
        annual_wages += other_income_annual

        # Step 3: Subtract standard deduction or Step 4b
        std_ded = STANDARD_DEDUCTION_2020.get(status, STANDARD_DEDUCTION_2020["SINGLE"])
        annual_std_ded = std_ded[freq] * Decimal(str(periods))
        if deductions_annual > annual_std_ded:
            annual_wages -= deductions_annual
        else:
            annual_wages -= annual_std_ded

        annual_wages = max(Decimal("0"), annual_wages)

        # Step 4: Calculate annual tax from bracket table
        annual_tax = self._apply_brackets(annual_wages, status)

        # Step 5: Add Step 4c extra withholding
        annual_tax += extra_withholding_annual

        # Step 6: De-annualize
        period_tax = _round(annual_tax / Decimal(str(periods)))
        return max(Decimal("0"), period_tax)

    def _calculate_pre2020_w4(
        self,
        wages: Decimal,
        freq: str,
        status: str,
        periods: int,
        allowances: int,
    ) -> Decimal:
        """Pre-2020 W-4 Percentage Method."""
        allowance_value = ALLOWANCE_PER_PERIOD.get(freq, Decimal("200"))
        adjusted_wages = wages - (allowance_value * Decimal(str(allowances)))
        adjusted_wages = max(Decimal("0"), adjusted_wages)

        # Annualize
        annual_wages = adjusted_wages * Decimal(str(periods))
        annual_tax = self._apply_brackets(annual_wages, status)

        period_tax = _round(annual_tax / Decimal(str(periods)))
        return max(Decimal("0"), period_tax)

    def _apply_brackets(self, annual_wages: Decimal, filing_status: str) -> Decimal:
        """Apply progressive tax brackets to annualized taxable income."""
        brackets = TAX_BRACKETS_ANNUAL.get(filing_status, TAX_BRACKETS_ANNUAL["SINGLE"])
        tax = Decimal("0")
        for i, (floor, rate, base_tax) in enumerate(brackets):
            if annual_wages <= floor:
                break
            # Check if income falls within this bracket
            if i + 1 < len(brackets):
                next_floor = brackets[i + 1][0]
                if annual_wages < next_floor:
                    tax = base_tax + _round((annual_wages - floor) * rate)
                    break
            else:
                # Highest bracket
                tax = base_tax + _round((annual_wages - floor) * rate)
        return tax

    def _periods_per_year(self, freq: str) -> int:
        return {"WEEKLY": 52, "BIWEEKLY": 26, "SEMIMONTHLY": 24, "MONTHLY": 12}.get(freq, 26)

    def calculate_supplemental_withholding(self, supplemental_wages: Decimal) -> Decimal:
        """
        Optional flat rate withholding for supplemental wages (bonuses, commissions).
        IRS 2025 supplemental rate: 22% for amounts <= $1M; 37% over $1M.
        """
        if supplemental_wages <= Decimal("1000000"):
            return _round(supplemental_wages * Decimal("0.22"))
        else:
            return _round(supplemental_wages * Decimal("0.37"))

    def estimate_annual_liability(
        self,
        annual_wages: Decimal,
        filing_status: str = "SINGLE",
    ) -> Decimal:
        """Estimate full-year federal income tax for a given annual wage."""
        return _round(self._apply_brackets(annual_wages, filing_status.upper()))
