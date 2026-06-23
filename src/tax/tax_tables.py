"""
tax_tables.py
Centralized Tax Rate Tables (2025).

Single source of truth for all federal and state tax brackets,
FICA rates, unemployment rates, and related constants used by
federal_tax.py, state_tax.py, and tax_reports.py.
"""

from decimal import Decimal
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
# Each bracket: (lower_bound, upper_bound_or_None, rate, base_tax)
TaxBracket = Tuple[Decimal, Decimal, Decimal, Decimal]


# ===========================================================================
# FEDERAL TAX CONSTANTS (2025)
# ===========================================================================

# IRS Publication 15 (Circular E) 2025
FEDERAL_TAX_YEAR = 2025

# Standard withholding allowance per period (IRS Pub 15-T Table 1)
FEDERAL_ALLOWANCE_PER_PERIOD: Dict[str, Decimal] = {
    "WEEKLY":       Decimal("100.00"),
    "BIWEEKLY":     Decimal("200.00"),
    "SEMIMONTHLY":  Decimal("216.67"),
    "MONTHLY":      Decimal("433.33"),
    "QUARTERLY":    Decimal("1300.00"),
    "ANNUAL":       Decimal("5200.00"),
}

# 2020+ W-4 standard deduction amounts per pay period (IRS Pub 15-T Table 2)
FEDERAL_STANDARD_DEDUCTION_2020: Dict[str, Dict[str, Decimal]] = {
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

# Annualized tax brackets for the percentage method (IRS Pub 15-T Table 2025)
# Format: (min_wages, max_wages_or_inf, tax_rate, base_tax_on_min)
INF = Decimal("999999999")

FEDERAL_BRACKETS_SINGLE_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("11925"),  Decimal("0.10"),  Decimal("0")),
    (Decimal("11925"),   Decimal("48475"),  Decimal("0.12"),  Decimal("1192.50")),
    (Decimal("48475"),   Decimal("103350"), Decimal("0.22"),  Decimal("5578.50")),
    (Decimal("103350"),  Decimal("197300"), Decimal("0.24"),  Decimal("17651.50")),
    (Decimal("197300"),  Decimal("250525"), Decimal("0.32"),  Decimal("40199.50")),
    (Decimal("250525"),  Decimal("626350"), Decimal("0.35"),  Decimal("57231.00")),
    (Decimal("626350"),  INF,               Decimal("0.37"),  Decimal("188769.75")),
]

FEDERAL_BRACKETS_MARRIED_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("23850"),  Decimal("0.10"),  Decimal("0")),
    (Decimal("23850"),   Decimal("96950"),  Decimal("0.12"),  Decimal("2385.00")),
    (Decimal("96950"),   Decimal("206700"), Decimal("0.22"),  Decimal("11157.00")),
    (Decimal("206700"),  Decimal("394600"), Decimal("0.24"),  Decimal("35302.00")),
    (Decimal("394600"),  Decimal("501050"), Decimal("0.32"),  Decimal("80398.00")),
    (Decimal("501050"),  Decimal("751600"), Decimal("0.35"),  Decimal("114462.00")),
    (Decimal("751600"),  INF,               Decimal("0.37"),  Decimal("202154.50")),
]

FEDERAL_BRACKETS_HOH_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("17000"),  Decimal("0.10"),  Decimal("0")),
    (Decimal("17000"),   Decimal("64850"),  Decimal("0.12"),  Decimal("1700.00")),
    (Decimal("64850"),   Decimal("103350"), Decimal("0.22"),  Decimal("7442.00")),
    (Decimal("103350"),  Decimal("197300"), Decimal("0.24"),  Decimal("15912.00")),
    (Decimal("197300"),  Decimal("250500"), Decimal("0.32"),  Decimal("38460.00")),
    (Decimal("250500"),  Decimal("626350"), Decimal("0.35"),  Decimal("55484.00")),
    (Decimal("626350"),  INF,               Decimal("0.37"),  Decimal("187031.50")),
]

# Maps filing status string to bracket list
FEDERAL_BRACKETS_2025: Dict[str, List[TaxBracket]] = {
    "SINGLE":            FEDERAL_BRACKETS_SINGLE_2025,
    "MARRIED":           FEDERAL_BRACKETS_MARRIED_2025,
    "HEAD_OF_HOUSEHOLD": FEDERAL_BRACKETS_HOH_2025,
}


# ===========================================================================
# FICA RATES (2025)
# ===========================================================================

SOCIAL_SECURITY_RATE = Decimal("0.062")           # Employee
SOCIAL_SECURITY_EMPLOYER_RATE = Decimal("0.062")  # Employer (same)
SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")      # Annual wage base 2025

MEDICARE_RATE = Decimal("0.0145")                 # Employee
MEDICARE_EMPLOYER_RATE = Decimal("0.0145")        # Employer (same)
ADDITIONAL_MEDICARE_RATE = Decimal("0.009")       # Employee only, over $200k
ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000") # Annual threshold


# ===========================================================================
# FEDERAL UNEMPLOYMENT (FUTA) RATES (2025)
# ===========================================================================

FUTA_GROSS_RATE = Decimal("0.06")      # Before SUTA credit
FUTA_SUTA_CREDIT = Decimal("0.054")   # Max credit for timely SUTA payments
FUTA_NET_RATE = Decimal("0.006")       # Effective net rate (0.6%)
FUTA_WAGE_BASE = Decimal("7000")       # Per-employee annual cap


# ===========================================================================
# STATE TAX BRACKETS (2025) — Selected States
# ===========================================================================
# Format: same as federal — (min, max, rate, base_tax)
# States with no income tax return empty lists.

# California (CA)
CA_BRACKETS_SINGLE_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("10412"),  Decimal("0.01"),  Decimal("0")),
    (Decimal("10412"),   Decimal("24684"),  Decimal("0.02"),  Decimal("104.12")),
    (Decimal("24684"),   Decimal("38959"),  Decimal("0.04"),  Decimal("389.56")),
    (Decimal("38959"),   Decimal("54081"),  Decimal("0.06"),  Decimal("960.56")),
    (Decimal("54081"),   Decimal("68350"),  Decimal("0.08"),  Decimal("1867.88")),
    (Decimal("68350"),   Decimal("349137"), Decimal("0.093"), Decimal("3009.40")),
    (Decimal("349137"),  Decimal("418961"), Decimal("0.103"), Decimal("29139.51")),
    (Decimal("418961"),  Decimal("698271"), Decimal("0.113"), Decimal("36331.41")),
    (Decimal("698271"),  Decimal("1000000"),Decimal("0.123"), Decimal("67897.14")),
    (Decimal("1000000"), INF,               Decimal("0.133"), Decimal("105027.26")),
]

CA_BRACKETS_MARRIED_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("20824"),  Decimal("0.01"),  Decimal("0")),
    (Decimal("20824"),   Decimal("49368"),  Decimal("0.02"),  Decimal("208.24")),
    (Decimal("49368"),   Decimal("77918"),  Decimal("0.04"),  Decimal("779.12")),
    (Decimal("77918"),   Decimal("108162"), Decimal("0.06"),  Decimal("1921.12")),
    (Decimal("108162"),  Decimal("136700"), Decimal("0.08"),  Decimal("3735.76")),
    (Decimal("136700"),  Decimal("698274"), Decimal("0.093"), Decimal("6018.80")),
    (Decimal("698274"),  Decimal("837922"), Decimal("0.103"), Decimal("58267.87")),
    (Decimal("837922"),  Decimal("1000000"),Decimal("0.113"), Decimal("72655.73")),
    (Decimal("1000000"), INF,               Decimal("0.123"), Decimal("90961.19")),
]

# New York (NY)
NY_BRACKETS_SINGLE_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("8500"),   Decimal("0.04"),   Decimal("0")),
    (Decimal("8500"),    Decimal("11700"),  Decimal("0.045"),  Decimal("340.00")),
    (Decimal("11700"),   Decimal("13900"),  Decimal("0.0525"), Decimal("484.00")),
    (Decimal("13900"),   Decimal("80650"),  Decimal("0.055"),  Decimal("599.50")),
    (Decimal("80650"),   Decimal("215400"), Decimal("0.06"),   Decimal("4271.25")),
    (Decimal("215400"),  Decimal("1077550"),Decimal("0.0685"), Decimal("12356.25")),
    (Decimal("1077550"), Decimal("5000000"),Decimal("0.0965"), Decimal("71413.68")),
    (Decimal("5000000"), INF,               Decimal("0.103"),  Decimal("449929.18")),
]

NY_BRACKETS_MARRIED_2025: List[TaxBracket] = [
    (Decimal("0"),       Decimal("17150"),  Decimal("0.04"),   Decimal("0")),
    (Decimal("17150"),   Decimal("23600"),  Decimal("0.045"),  Decimal("686.00")),
    (Decimal("23600"),   Decimal("27900"),  Decimal("0.0525"), Decimal("976.25")),
    (Decimal("27900"),   Decimal("161550"), Decimal("0.055"),  Decimal("1202.00")),
    (Decimal("161550"),  Decimal("323200"), Decimal("0.06"),   Decimal("8551.75")),
    (Decimal("323200"),  Decimal("2155350"),Decimal("0.0685"), Decimal("18251.75")),
    (Decimal("2155350"), Decimal("5000000"),Decimal("0.0965"), Decimal("143769.40")),
    (Decimal("5000000"), INF,               Decimal("0.103"),  Decimal("418469.90")),
]

# Illinois (IL) — flat tax
IL_FLAT_RATE = Decimal("0.0495")   # 4.95% flat for all filers

# Texas, Florida, Nevada, Washington, Wyoming, South Dakota, Alaska
# — no state income tax
NO_INCOME_TAX_STATES = {"TX", "FL", "NV", "WA", "WY", "SD", "AK", "TN", "NH"}


# Lookup: state_code -> {filing_status -> bracket_list}
# For flat-rate states, use a single bracket spanning all income.
STATE_BRACKETS_2025: Dict[str, Dict[str, List[TaxBracket]]] = {
    "CA": {
        "SINGLE":            CA_BRACKETS_SINGLE_2025,
        "MARRIED":           CA_BRACKETS_MARRIED_2025,
        "HEAD_OF_HOUSEHOLD": CA_BRACKETS_SINGLE_2025,  # CA uses single brackets for HOH
    },
    "NY": {
        "SINGLE":            NY_BRACKETS_SINGLE_2025,
        "MARRIED":           NY_BRACKETS_MARRIED_2025,
        "HEAD_OF_HOUSEHOLD": NY_BRACKETS_SINGLE_2025,
    },
    "IL": {
        "SINGLE":   [(Decimal("0"), INF, IL_FLAT_RATE, Decimal("0"))],
        "MARRIED":  [(Decimal("0"), INF, IL_FLAT_RATE, Decimal("0"))],
        "HEAD_OF_HOUSEHOLD": [(Decimal("0"), INF, IL_FLAT_RATE, Decimal("0"))],
    },
    # No-income-tax states get empty brackets (handled by StateTaxCalculator)
    **{state: {"SINGLE": [], "MARRIED": [], "HEAD_OF_HOUSEHOLD": []}
       for state in NO_INCOME_TAX_STATES},
}


# ===========================================================================
# STATE UNEMPLOYMENT INSURANCE (SUTA) RATES (2025)
# ===========================================================================
# New employer rates and wage bases (varies by state each year)
# Format: {state: (new_employer_rate, wage_base)}

SUTA_RATES_2025: Dict[str, Tuple[Decimal, Decimal]] = {
    "CA": (Decimal("0.034"), Decimal("7000")),
    "NY": (Decimal("0.0341"), Decimal("12800")),
    "TX": (Decimal("0.027"), Decimal("9000")),
    "FL": (Decimal("0.027"), Decimal("7000")),
    "IL": (Decimal("0.037"), Decimal("13590")),
    "WA": (Decimal("0.01"), Decimal("72800")),
    "NV": (Decimal("0.03"), Decimal("40100")),
    "GA": (Decimal("0.0270"), Decimal("9500")),
    "CO": (Decimal("0.017"), Decimal("23800")),
    "AZ": (Decimal("0.02"), Decimal("8000")),
    "OH": (Decimal("0.027"), Decimal("9000")),
    "PA": (Decimal("0.0358"), Decimal("10000")),
    "MA": (Decimal("0.029"), Decimal("15000")),
    "MN": (Decimal("0.011"), Decimal("42000")),
    "MI": (Decimal("0.027"), Decimal("9500")),
}


# ===========================================================================
# Helper functions
# ===========================================================================

def get_federal_brackets(filing_status: str) -> List[TaxBracket]:
    """Return 2025 federal tax brackets for a given filing status."""
    status = filing_status.upper().replace(" ", "_")
    brackets = FEDERAL_BRACKETS_2025.get(status)
    if brackets is None:
        raise ValueError(
            f"Unknown filing status '{filing_status}'. "
            f"Use: SINGLE, MARRIED, or HEAD_OF_HOUSEHOLD."
        )
    return brackets


def get_state_brackets(state_code: str, filing_status: str) -> List[TaxBracket]:
    """
    Return state tax brackets for a given state and filing status.
    Returns an empty list for no-income-tax states.
    Raises ValueError for unsupported states.
    """
    state = state_code.upper()
    if state in NO_INCOME_TAX_STATES:
        return []
    state_table = STATE_BRACKETS_2025.get(state)
    if state_table is None:
        raise NotImplementedError(
            f"State '{state}' tax brackets not yet implemented. "
            "Add the state to STATE_BRACKETS_2025 in tax_tables.py."
        )
    status = filing_status.upper().replace(" ", "_")
    brackets = state_table.get(status)
    if brackets is None:
        raise ValueError(f"Unknown filing status '{filing_status}' for state {state}.")
    return brackets


def calculate_tax_from_brackets(
    annual_wages: Decimal,
    brackets: List[TaxBracket],
) -> Decimal:
    """
    Apply a progressive bracket table to annualized wages.
    Returns annual tax amount.
    """
    from decimal import ROUND_HALF_UP
    tax = Decimal("0")
    for lower, upper, rate, base in brackets:
        if annual_wages <= lower:
            break
        taxable = min(annual_wages, upper) - lower
        tax = base + (taxable * rate)
    return tax.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_suta_rate(state_code: str) -> Tuple[Decimal, Decimal]:
    """
    Return (rate, wage_base) for a state's SUTA.
    Returns (0, 0) for states not in the table.
    """
    return SUTA_RATES_2025.get(state_code.upper(), (Decimal("0"), Decimal("0")))
