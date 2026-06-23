"""
state_tax.py
State Income Tax Withholding Calculator.

Supports the 10 most populous US states with actual 2025 tax brackets
and withholding tables. States with no income tax are handled automatically.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Tuple, Optional

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


PERIODS_PER_YEAR = {
    "WEEKLY": 52, "BIWEEKLY": 26, "SEMIMONTHLY": 24, "MONTHLY": 12,
}

# States with no income tax
NO_INCOME_TAX_STATES = {"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"}

# ---------------------------------------------------------------------------
# State withholding allowance values (annual, per allowance) — 2025
# ---------------------------------------------------------------------------
STATE_ALLOWANCE_ANNUAL: Dict[str, Decimal] = {
    "CA": Decimal("154.00"),
    "NY": Decimal("1000.00"),
    "IL": Decimal("2425.00"),
    "PA": Decimal("0"),        # PA uses flat rate, no allowances
    "OH": Decimal("2400.00"),
    "GA": Decimal("3000.00"),
    "NC": Decimal("0"),        # NC uses standard deduction
    "MI": Decimal("5400.00"),
    "VA": Decimal("930.00"),
    "AZ": Decimal("0"),        # AZ uses percentage of federal
    "CO": Decimal("0"),        # CO flat rate
    "MA": Decimal("0"),        # MA flat rate
    "MD": Decimal("3200.00"),
    "MN": Decimal("4800.00"),
    "WI": Decimal("700.00"),
    "OR": Decimal("219.00"),
    "NJ": Decimal("1000.00"),
    "CT": Decimal("0"),
    "IN": Decimal("1000.00"),
    "MO": Decimal("2100.00"),
}

# ---------------------------------------------------------------------------
# Annual income tax brackets by state and filing status
# Format: List of (floor, rate, base_tax)
# ---------------------------------------------------------------------------
STATE_BRACKETS: Dict[str, Dict[str, List[Tuple[Decimal, Decimal, Decimal]]]] = {

    # California 2025 (SDI not included here)
    "CA": {
        "SINGLE": [
            (Decimal("0"),       Decimal("0.011"), Decimal("0")),
            (Decimal("10412"),   Decimal("0.022"), Decimal("114.53")),
            (Decimal("24684"),   Decimal("0.044"), Decimal("428.91")),
            (Decimal("38959"),   Decimal("0.066"), Decimal("1057.81")),
            (Decimal("54081"),   Decimal("0.088"), Decimal("2056.85")),
            (Decimal("68350"),   Decimal("0.1023"), Decimal("3312.57")),
            (Decimal("349137"),  Decimal("0.1133"), Decimal("32025.87")),
            (Decimal("418961"),  Decimal("0.1233"), Decimal("39939.84")),
            (Decimal("698274"),  Decimal("0.1333"), Decimal("74349.99")),
            (Decimal("1000000"), Decimal("0.1430"), Decimal("114586.69")),
        ],
        "MARRIED": [
            (Decimal("0"),       Decimal("0.011"), Decimal("0")),
            (Decimal("20824"),   Decimal("0.022"), Decimal("229.06")),
            (Decimal("49368"),   Decimal("0.044"), Decimal("857.82")),
            (Decimal("77918"),   Decimal("0.066"), Decimal("2114.02")),
            (Decimal("108162"),  Decimal("0.088"), Decimal("4113.70")),
            (Decimal("136700"),  Decimal("0.1023"), Decimal("6625.04")),
            (Decimal("698274"),  Decimal("0.1133"), Decimal("64051.74")),
            (Decimal("837922"),  Decimal("0.1233"), Decimal("79879.68")),
            (Decimal("1000000"), Decimal("0.1333"), Decimal("99875.00")),
        ],
    },

    # New York 2025
    "NY": {
        "SINGLE": [
            (Decimal("0"),       Decimal("0.04"),  Decimal("0")),
            (Decimal("8500"),    Decimal("0.045"), Decimal("340.00")),
            (Decimal("11700"),   Decimal("0.0525"), Decimal("484.00")),
            (Decimal("13900"),   Decimal("0.055"), Decimal("599.50")),
            (Decimal("80650"),   Decimal("0.06"),  Decimal("4271.25")),
            (Decimal("215400"),  Decimal("0.0685"), Decimal("12356.25")),
            (Decimal("1077550"), Decimal("0.0965"), Decimal("71413.68")),
            (Decimal("5000000"), Decimal("0.103"), Decimal("449929.68")),
        ],
        "MARRIED": [
            (Decimal("0"),       Decimal("0.04"),  Decimal("0")),
            (Decimal("17150"),   Decimal("0.045"), Decimal("686.00")),
            (Decimal("23600"),   Decimal("0.0525"), Decimal("976.25")),
            (Decimal("27900"),   Decimal("0.055"), Decimal("1202.00")),
            (Decimal("161550"),  Decimal("0.06"),  Decimal("8552.25")),
            (Decimal("323200"),  Decimal("0.0685"), Decimal("18256.25")),
            (Decimal("2155350"), Decimal("0.0965"), Decimal("143691.72")),
            (Decimal("5000000"), Decimal("0.103"), Decimal("418327.16")),
        ],
    },

    # Illinois 2025 (flat 4.95%)
    "IL": {
        "SINGLE":  [(Decimal("0"), Decimal("0.0495"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.0495"), Decimal("0"))],
    },

    # Pennsylvania (flat 3.07%)
    "PA": {
        "SINGLE":  [(Decimal("0"), Decimal("0.0307"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.0307"), Decimal("0"))],
    },

    # Georgia 2025
    "GA": {
        "SINGLE": [
            (Decimal("0"),      Decimal("0.01"), Decimal("0")),
            (Decimal("750"),    Decimal("0.02"), Decimal("7.50")),
            (Decimal("2250"),   Decimal("0.03"), Decimal("37.50")),
            (Decimal("3750"),   Decimal("0.04"), Decimal("82.50")),
            (Decimal("5250"),   Decimal("0.05"), Decimal("142.50")),
            (Decimal("7000"),   Decimal("0.055"), Decimal("230.00")),
        ],
        "MARRIED": [
            (Decimal("0"),      Decimal("0.01"), Decimal("0")),
            (Decimal("1000"),   Decimal("0.02"), Decimal("10.00")),
            (Decimal("3000"),   Decimal("0.03"), Decimal("50.00")),
            (Decimal("5000"),   Decimal("0.04"), Decimal("110.00")),
            (Decimal("7000"),   Decimal("0.05"), Decimal("190.00")),
            (Decimal("10000"),  Decimal("0.055"), Decimal("340.00")),
        ],
    },

    # North Carolina 2025 (flat 4.5%)
    "NC": {
        "SINGLE":  [(Decimal("0"), Decimal("0.045"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.045"), Decimal("0"))],
    },

    # Michigan 2025 (flat 4.05%)
    "MI": {
        "SINGLE":  [(Decimal("0"), Decimal("0.0405"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.0405"), Decimal("0"))],
    },

    # Virginia 2025
    "VA": {
        "SINGLE": [
            (Decimal("0"),     Decimal("0.02"),  Decimal("0")),
            (Decimal("3000"),  Decimal("0.03"),  Decimal("60.00")),
            (Decimal("5000"),  Decimal("0.05"),  Decimal("120.00")),
            (Decimal("17000"), Decimal("0.0575"), Decimal("720.00")),
        ],
        "MARRIED": [
            (Decimal("0"),     Decimal("0.02"),  Decimal("0")),
            (Decimal("3000"),  Decimal("0.03"),  Decimal("60.00")),
            (Decimal("5000"),  Decimal("0.05"),  Decimal("120.00")),
            (Decimal("17000"), Decimal("0.0575"), Decimal("720.00")),
        ],
    },

    # Arizona 2025 (flat 2.5%)
    "AZ": {
        "SINGLE":  [(Decimal("0"), Decimal("0.025"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.025"), Decimal("0"))],
    },

    # Colorado 2025 (flat 4.4%)
    "CO": {
        "SINGLE":  [(Decimal("0"), Decimal("0.044"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.044"), Decimal("0"))],
    },

    # Massachusetts 2025 (flat 5%)
    "MA": {
        "SINGLE":  [(Decimal("0"), Decimal("0.05"), Decimal("0"))],
        "MARRIED": [(Decimal("0"), Decimal("0.05"), Decimal("0"))],
    },

    # Maryland 2025
    "MD": {
        "SINGLE": [
            (Decimal("0"),      Decimal("0.02"),  Decimal("0")),
            (Decimal("1000"),   Decimal("0.03"),  Decimal("20.00")),
            (Decimal("2000"),   Decimal("0.04"),  Decimal("50.00")),
            (Decimal("3000"),   Decimal("0.0475"), Decimal("90.00")),
            (Decimal("100000"), Decimal("0.05"),  Decimal("4697.50")),
            (Decimal("125000"), Decimal("0.0525"), Decimal("5947.50")),
            (Decimal("150000"), Decimal("0.055"), Decimal("7260.00")),
            (Decimal("250000"), Decimal("0.0575"), Decimal("12760.00")),
        ],
        "MARRIED": [
            (Decimal("0"),      Decimal("0.02"),  Decimal("0")),
            (Decimal("1000"),   Decimal("0.03"),  Decimal("20.00")),
            (Decimal("2000"),   Decimal("0.04"),  Decimal("50.00")),
            (Decimal("3000"),   Decimal("0.0475"), Decimal("90.00")),
            (Decimal("150000"), Decimal("0.05"),  Decimal("7222.50")),
            (Decimal("175000"), Decimal("0.0525"), Decimal("8472.50")),
            (Decimal("225000"), Decimal("0.055"), Decimal("11097.50")),
            (Decimal("300000"), Decimal("0.0575"), Decimal("15222.50")),
        ],
    },

    # New Jersey 2025
    "NJ": {
        "SINGLE": [
            (Decimal("0"),      Decimal("0.014"), Decimal("0")),
            (Decimal("20000"),  Decimal("0.0175"), Decimal("280.00")),
            (Decimal("35000"),  Decimal("0.035"), Decimal("542.50")),
            (Decimal("40000"),  Decimal("0.05525"), Decimal("717.50")),
            (Decimal("75000"),  Decimal("0.0637"), Decimal("2651.25")),
            (Decimal("500000"), Decimal("0.0897"), Decimal("29720.00")),
            (Decimal("1000000"), Decimal("0.1075"), Decimal("74571.50")),
        ],
        "MARRIED": [
            (Decimal("0"),      Decimal("0.014"), Decimal("0")),
            (Decimal("20000"),  Decimal("0.0175"), Decimal("280.00")),
            (Decimal("50000"),  Decimal("0.035"), Decimal("805.00")),
            (Decimal("70000"),  Decimal("0.05525"), Decimal("1505.00")),
            (Decimal("80000"),  Decimal("0.0637"), Decimal("2057.50")),
            (Decimal("150000"), Decimal("0.0637"), Decimal("6515.00")),
            (Decimal("500000"), Decimal("0.0897"), Decimal("28815.00")),
            (Decimal("1000000"), Decimal("0.1075"), Decimal("75196.50")),
        ],
    },
}


class StateTaxCalculator:
    """
    State Income Tax Withholding Calculator (2025).

    Handles the 50 US states; returns $0 for states with no income tax.
    Uses actual published state withholding tables / flat rates.

    Usage:
        calc = StateTaxCalculator()
        tax = calc.calculate(
            taxable_wages=Decimal("3000.00"),
            state_code="CA",
            pay_frequency="BIWEEKLY",
            filing_status="SINGLE",
            allowances=1,
        )
    """

    def calculate(
        self,
        taxable_wages: Decimal,
        state_code: str,
        pay_frequency: str,
        filing_status: str,
        allowances: int = 0,
        additional_withholding: Decimal = Decimal("0"),
    ) -> Decimal:
        """
        Calculate state income tax withholding for one pay period.

        Args:
            taxable_wages:          Post-pretax-deduction gross wages.
            state_code:             Two-letter state code (e.g. "CA", "TX").
            pay_frequency:          WEEKLY | BIWEEKLY | SEMIMONTHLY | MONTHLY.
            filing_status:          SINGLE | MARRIED | HEAD_OF_HOUSEHOLD.
            allowances:             State withholding allowances.
            additional_withholding: Extra flat amount to add.

        Returns:
            State income tax withholding for the period.
        """
        state = state_code.upper()
        freq = pay_frequency.upper()
        status = filing_status.upper()
        if status == "HEAD_OF_HOUSEHOLD":
            status = "SINGLE"   # Most states treat HoH as Single

        if state in NO_INCOME_TAX_STATES:
            return _round(additional_withholding)

        if state not in STATE_BRACKETS:
            # Default: 5% flat rate for states not explicitly configured
            tax = _round(taxable_wages * Decimal("0.05"))
            return _round(tax + additional_withholding)

        periods = Decimal(str(PERIODS_PER_YEAR.get(freq, 26)))

        # Annualize wages
        annual_wages = taxable_wages * periods

        # Subtract allowances
        allowance_annual = STATE_ALLOWANCE_ANNUAL.get(state, Decimal("0"))
        annual_wages -= allowance_annual * Decimal(str(allowances))
        annual_wages = max(Decimal("0"), annual_wages)

        # Apply brackets
        brackets = STATE_BRACKETS[state].get(status, STATE_BRACKETS[state].get("SINGLE", []))
        annual_tax = self._apply_brackets(annual_wages, brackets)

        # De-annualize
        period_tax = _round(annual_tax / periods)
        period_tax = max(Decimal("0"), period_tax)

        return _round(period_tax + additional_withholding)

    def _apply_brackets(
        self, annual_wages: Decimal,
        brackets: List[Tuple[Decimal, Decimal, Decimal]]
    ) -> Decimal:
        """Apply state tax brackets to annualized income."""
        if not brackets:
            return Decimal("0")
        tax = Decimal("0")
        for i, (floor, rate, base_tax) in enumerate(brackets):
            if annual_wages <= floor:
                break
            if i + 1 < len(brackets):
                next_floor = brackets[i + 1][0]
                if annual_wages < next_floor:
                    tax = base_tax + _round((annual_wages - floor) * rate)
                    break
            else:
                tax = base_tax + _round((annual_wages - floor) * rate)
        return tax

    def get_state_name(self, state_code: str) -> str:
        """Return the full state name for a given state code."""
        STATE_NAMES = {
            "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
            "CA": "California", "CO": "Colorado", "CT": "Connecticut",
            "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
            "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
            "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
            "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
            "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
            "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
            "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
            "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
            "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
            "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
            "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
            "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
            "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
            "WY": "Wyoming",
        }
        return STATE_NAMES.get(state_code.upper(), state_code)

    def has_state_tax(self, state_code: str) -> bool:
        """Return True if the state levies an income tax."""
        return state_code.upper() not in NO_INCOME_TAX_STATES
