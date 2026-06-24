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
        "WEEKLY":      Decimal("299.04"),
        "BIWEEKLY":    Decimal("598.08"),
        "SEMIMONTHLY": Decimal("647.92"),
        "MONTHLY":     Decimal("1295.83"),
    },
    "MARRIED": {
        "WEEKLY":      Decimal("598.08"),
        "BIWEEKLY":    Decimal("1196.15"),
        "SEMIMONTHLY": Decimal("1295.83"),
        "MONTHLY":     Decimal("2591.67"),
    },
    "HEAD_OF_HOUSEHOLD": {
        "WEEKLY":      Decimal("447.12"),
        "BIWEEKLY":    Decimal("894.23"),
        "SEMIMONTHLY": Decimal("968.75"),
        "MONTHLY":     Decimal("1937.50"),
    },
}

# ---------------------------------------------------------------------------
# 2025 Percentage Method Tax Brackets (Annual)
# Format: (bracket_floor, rate, base_tax_at_floor)
# IRS Publication 15-T Table 2
# ---------------------------------------------------------------------------
TAX_BRACKETS_ANNUAL: Dict[str, List[Tuple[Decimal, Decimal, Decimal]]] = {
    "SINGLE": [
        (Decimal("0"),      Decimal("0.10"), Decimal("0")),
        (Decimal("11925"),  Decimal("0.12"), Decimal("1192.50")),
        (Decimal("48475"),  Decimal("0.22"), Decimal("5578.50")),
        (Decimal("103350"), Decimal("0.24"), Decimal("17651.00")),
        (Decimal("197300"), Decimal("0.32"), Decimal("40199.00")),
        (Decimal("250525"), Decimal("0.35"), Decimal("57231.00")),
        (Decimal("626350"), Decimal("0.37"), Decimal("188769.75")),
    ],
    "MARRIED": [
        (Decimal("0"),      Decimal("0.10"), Decimal("0")),
        (Decimal("23850"),  Decimal("0.12"), Decimal("2385.00")),
        (Decimal("96950"),  Decimal("0.22"), Decimal("11157.00")),
        (Decimal("206700"), Decimal("0.24"), Decimal("35302.00")),
        (Decimal("394600"), Decimal("0.32"), Decimal("80398.00")),
        (Decimal("501050"), Decimal("0.35"), Decimal("114462.00")),
        (Decimal("751600"), Decimal("0.37"), Decimal("202154.50")),
    ],
    "HEAD_OF_HOUSEHOLD": [
        (Decimal("0"),      Decimal("0.10"), Decimal("0")),
        (Decimal("17000"),  Decimal("0.12"), Decimal("1700.00")),
        (Decimal("64850"),  Decimal("0.22"), Decimal("7442.00")),
        (Decimal("103350"), Decimal("0.24"), Decimal("15912.00")),
        (Decimal("197300"), Decimal("0.32"), Decimal("38460.00")),
        (Decimal("250500"), Decimal("0.35"), Decimal("55484.00")),
        (Decimal("626350"), Decimal("0.37"), Decimal("187031.50")),
    ],
}


class FederalTaxCalculator:
    """
    IRS Percentage Method Federal Income Tax Withholding Calculator (2025).

    Supports:
    - Pre-2020 W-4 (allowances-based): pass allowances > 0 or use_2020_w4=False
    - 2020+ W-4 (standard deduction method): use_2020_w4=True (default)
    - Additional flat withholding
    - All filing statuses: SINGLE, MARRIED, HEAD_OF_HOUSEHOLD
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
            taxable_wages:           Pre-tax gross wages after pre-tax deductions.
            pay_frequency:           WEEKLY | BIWEEKLY | SEMIMONTHLY | MONTHLY.
            filing_status:           SINGLE | MARRIED | HEAD_OF_HOUSEHOLD.
            allowances:              Number of withholding allowances (pre-2020 W-4).
                                     When allowances > 0, automatically uses the
                                     pre-2020 allowance method regardless of use_2020_w4.
            additional_withholding:  Flat additional amount to withhold each period.
            use_2020_w4:             If True AND allowances == 0, use 2020+ standard
                                     deduction method. Ignored when allowances > 0.
            other_income_annual:     Step 4a on 2020+ W-4 (annualized).
            deductions_annual:       Step 4b on 2020+ W-4 (annualized).
            extra_withholding_annual: Step 4c on 2020+ W-4 (annualized).

        Returns:
            Decimal: Tax amount to withhold for the pay period.
        """
        freq = pay_frequency.upper()
        status = filing_status.upper()
        periods = self._periods_per_year(freq)

        # If allowances are specified, use pre-2020 allowance method.
        # This ensures allowances actually reduce withholding as expected.
        if allowances > 0:
            effective_use_2020 = False
        else:
            effective_use_2020 = use_2020_w4

        if effective_use_2020:
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
        """Apply progressive tax brackets to annualized wages."""
        brackets = TAX_BRACKETS_ANNUAL.get(filing_status, TAX_BRACKETS_ANNUAL["SINGLE"])
        annual_tax = Decimal("0")
        for floor, rate, base_tax in reversed(brackets):
            if annual_wages > floor:
                annual_tax = base_tax + (annual_wages - floor) * rate
                break
        return annual_tax

    def _periods_per_year(self, freq: str) -> int:
        """Return number of pay periods per year for a given frequency."""
        mapping = {
            "WEEKLY": 52,
            "BIWEEKLY": 26,
            "SEMIMONTHLY": 24,
            "MONTHLY": 12,
        }
        return mapping.get(freq, 26)


class FICACalculator:
    """
    FICA (Social Security and Medicare) Tax Calculator (2025).

    2025 Rates:
    - Social Security: 6.2% employee, 6.2% employer (wage base $176,100)
    - Medicare: 1.45% employee, 1.45% employer (no wage base limit)
    - Additional Medicare: 0.9% employee only on wages > $200,000
    """

    SS_RATE = Decimal("0.062")
    SS_WAGE_BASE_2025 = Decimal("176100")
    MEDICARE_RATE = Decimal("0.0145")
    ADD_MEDICARE_RATE = Decimal("0.009")
    ADD_MEDICARE_THRESHOLD = Decimal("200000")

    def calculate(
        self,
        gross_wages: Decimal,
        ytd_wages: Decimal = Decimal("0"),
    ) -> dict:
        """
        Calculate FICA taxes for a pay period.

        Args:
            gross_wages: Gross wages for this pay period.
            ytd_wages:   Year-to-date wages before this period.

        Returns:
            dict with keys: social_security, medicare, additional_medicare,
                            total_employee, total_employer
        """
        # Social Security - subject to wage base
        ss_taxable = max(
            Decimal("0"),
            min(gross_wages, self.SS_WAGE_BASE_2025 - ytd_wages)
        )
        ss_tax = _round(ss_taxable * self.SS_RATE)

        # Medicare - no wage base limit
        medicare_tax = _round(gross_wages * self.MEDICARE_RATE)

        # Additional Medicare Tax (employee only, on wages > $200,000 YTD)
        add_medicare = Decimal("0")
        ytd_after = ytd_wages + gross_wages
        if ytd_after > self.ADD_MEDICARE_THRESHOLD:
            taxable_for_add = ytd_after - max(ytd_wages, self.ADD_MEDICARE_THRESHOLD)
            add_medicare = _round(taxable_for_add * self.ADD_MEDICARE_RATE)

        total_employee = _round(ss_tax + medicare_tax + add_medicare)
        total_employer = _round(ss_tax + medicare_tax)  # Employer has no add. Medicare

        return {
            "social_security": ss_tax,
            "medicare": medicare_tax,
            "additional_medicare": add_medicare,
            "total_employee": total_employee,
            "total_employer": total_employer,
        }
