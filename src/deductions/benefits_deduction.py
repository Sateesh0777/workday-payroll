"""
benefits_deduction.py
Employee Benefits Deduction Calculator.

Processes health insurance (medical/dental/vision), FSA, HSA,
life insurance, and other voluntary benefit deductions.
Distinguishes between pre-tax (Section 125 cafeteria plan) and
post-tax deductions, and calculates employer contributions.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Benefit plan types and their tax treatment
# ---------------------------------------------------------------------------

PRETAX_BENEFIT_TYPES = {
    "MEDICAL",            # Health insurance premiums (Section 125)
    "DENTAL",             # Dental insurance (Section 125)
    "VISION",             # Vision insurance (Section 125)
    "FSA_HEALTH",         # Health Flexible Spending Account
    "FSA_DEPENDENT_CARE", # Dependent Care FSA (up to $5,000/year)
    "HSA",                # Health Savings Account (HDHP only)
    "GROUP_LIFE_PRETAX",  # Employer-sponsored life up to $50k face value
    "TRANSIT",            # Commuter transit (Section 132)
    "PARKING",            # Commuter parking (Section 132)
}

POSTTAX_BENEFIT_TYPES = {
    "SUPPLEMENTAL_LIFE",  # Employee-paid additional life insurance
    "CRITICAL_ILLNESS",   # Critical illness insurance
    "ACCIDENT",           # Accident insurance
    "HOSPITAL_INDEMNITY", # Hospital indemnity
    "LEGAL_SERVICES",     # Legal plan
    "PET_INSURANCE",      # Pet insurance
    "CHARITABLE",         # Charitable contributions
    "LOAN_REPAYMENT",     # Student loan repayment (post-tax)
}

# 2025 IRS contribution limits
IRS_LIMITS_2025 = {
    "FSA_HEALTH":         Decimal("3300"),    # Annual IRS max
    "FSA_DEPENDENT_CARE": Decimal("5000"),    # Annual IRS max
    "HSA_SINGLE":         Decimal("4300"),    # Annual HDHP single
    "HSA_FAMILY":         Decimal("8550"),    # Annual HDHP family
    "HSA_CATCHUP":        Decimal("1000"),    # Age 55+ additional
    "TRANSIT_MONTHLY":    Decimal("325"),     # Monthly transit limit
    "PARKING_MONTHLY":    Decimal("325"),     # Monthly parking limit
}


@dataclass
class BenefitElection:
    """A single benefit plan election for an employee."""
    benefit_type: str          # e.g. "MEDICAL", "DENTAL"
    plan_name: str             # e.g. "Blue Shield PPO"
    coverage_tier: str         # EMPLOYEE | EMPLOYEE_SPOUSE | EMPLOYEE_CHILDREN | FAMILY
    employee_premium: Decimal  # Employee per-period contribution
    employer_premium: Decimal  # Employer per-period contribution
    is_pretax: bool = True
    annual_limit: Optional[Decimal] = None
    ytd_employee: Decimal = Decimal("0")
    ytd_employer: Decimal = Decimal("0")


@dataclass
class BenefitsDeductionResult:
    """Result of benefits deduction calculation for one pay period."""
    pretax_total: Decimal = Decimal("0")
    posttax_total: Decimal = Decimal("0")
    employer_contribution: Decimal = Decimal("0")
    line_items: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class BenefitsDeductionCalculator:
    """
    Employee Benefits Deduction Calculator.

    Takes a list of benefit elections (as returned by the Workday API)
    and computes pre-tax deductions, post-tax deductions, and employer
    contributions for the pay period.

    Usage:
        calc = BenefitsDeductionCalculator()
        result = calc.calculate(elections_from_workday)
        pretax = result.pretax_total
        posttax = result.posttax_total
        employer = result.employer_contribution
    """

    def calculate(self, elections: List[Dict]) -> BenefitsDeductionResult:
        """
        Calculate benefits deductions for a pay period.

        Args:
            elections: List of benefit election dicts from Workday API.
                       Each dict should have keys:
                       - benefitType, planName, coverageTier
                       - employeePremium, employerPremium
                       - isPretax (optional, defaults based on type)
                       - annualLimit (optional)
                       - ytdEmployee, ytdEmployer

        Returns:
            BenefitsDeductionResult with pre/post-tax totals and employer contributions.
        """
        result = BenefitsDeductionResult()

        for election in elections:
            benefit_type = election.get("benefitType", "").upper()
            plan_name = election.get("planName", benefit_type)
            employee_premium = Decimal(str(election.get("employeePremium", 0)))
            employer_premium = Decimal(str(election.get("employerPremium", 0)))
            ytd_employee = Decimal(str(election.get("ytdEmployee", 0)))
            annual_limit = election.get("annualLimit")
            if annual_limit is not None:
                annual_limit = Decimal(str(annual_limit))

            # Determine tax treatment
            is_pretax = election.get("isPretax",
                benefit_type in PRETAX_BENEFIT_TYPES
            )

            # Apply annual limit check (e.g. FSA, HSA)
            if annual_limit is not None:
                remaining = max(Decimal("0"), annual_limit - ytd_employee)
                if employee_premium > remaining:
                    result.warnings.append(
                        f"{plan_name}: Employee premium {employee_premium} exceeds "
                        f"remaining annual limit {remaining}. Capping at {remaining}."
                    )
                    employee_premium = remaining

            # Apply IRS limits for special account types
            employee_premium = self._apply_irs_limits(
                benefit_type, employee_premium, ytd_employee
            )

            # Accumulate totals
            if is_pretax:
                result.pretax_total += employee_premium
            else:
                result.posttax_total += employee_premium

            result.employer_contribution += employer_premium

            # Record line item
            result.line_items.append({
                "benefitType": benefit_type,
                "planName": plan_name,
                "employeePremium": _round(employee_premium),
                "employerPremium": _round(employer_premium),
                "isPretax": is_pretax,
            })

        result.pretax_total = _round(result.pretax_total)
        result.posttax_total = _round(result.posttax_total)
        result.employer_contribution = _round(result.employer_contribution)
        return result

    def _apply_irs_limits(
        self,
        benefit_type: str,
        employee_premium: Decimal,
        ytd_employee: Decimal,
    ) -> Decimal:
        """Cap contributions at IRS annual limits where applicable."""
        annual_limit = None

        if benefit_type == "FSA_HEALTH":
            annual_limit = IRS_LIMITS_2025["FSA_HEALTH"]
        elif benefit_type == "FSA_DEPENDENT_CARE":
            annual_limit = IRS_LIMITS_2025["FSA_DEPENDENT_CARE"]
        elif benefit_type in ("HSA_SINGLE", "HSA"):
            annual_limit = IRS_LIMITS_2025["HSA_SINGLE"]
        elif benefit_type == "HSA_FAMILY":
            annual_limit = IRS_LIMITS_2025["HSA_FAMILY"]

        if annual_limit is not None:
            remaining = max(Decimal("0"), annual_limit - ytd_employee)
            employee_premium = min(employee_premium, remaining)

        return employee_premium

    def calculate_from_elections(self, elections: List[BenefitElection]) -> BenefitsDeductionResult:
        """
        Typed version: accepts BenefitElection dataclass objects directly.
        """
        raw = []
        for e in elections:
            raw.append({
                "benefitType": e.benefit_type,
                "planName": e.plan_name,
                "employeePremium": float(e.employee_premium),
                "employerPremium": float(e.employer_premium),
                "isPretax": e.is_pretax,
                "annualLimit": float(e.annual_limit) if e.annual_limit else None,
                "ytdEmployee": float(e.ytd_employee),
                "ytdEmployer": float(e.ytd_employer),
            })
        return self.calculate(raw)

    def imputed_income(
        self,
        employer_life_face_value: Decimal,
        employee_age: int,
        periods_per_year: int = 26,
    ) -> Decimal:
        """
        Calculate taxable imputed income for employer-paid life insurance
        exceeding $50,000 face value (IRS Table I rates).
        Per $1,000 of coverage over $50,000, per month.
        """
        IRS_TABLE_I_MONTHLY_PER_1000 = {
            (25, 29): Decimal("0.06"),
            (30, 34): Decimal("0.08"),
            (35, 39): Decimal("0.09"),
            (40, 44): Decimal("0.10"),
            (45, 49): Decimal("0.15"),
            (50, 54): Decimal("0.23"),
            (55, 59): Decimal("0.43"),
            (60, 64): Decimal("0.66"),
            (65, 69): Decimal("1.27"),
            (70, 99): Decimal("2.06"),
        }

        excess_coverage = max(Decimal("0"), employer_life_face_value - Decimal("50000"))
        if excess_coverage == 0:
            return Decimal("0")

        monthly_rate = Decimal("0.10")  # default
        for (low, high), rate in IRS_TABLE_I_MONTHLY_PER_1000.items():
            if low <= employee_age <= high:
                monthly_rate = rate
                break

        excess_thousands = excess_coverage / Decimal("1000")
        annual_imputed = _round(excess_thousands * monthly_rate * 12)
        period_imputed = _round(annual_imputed / Decimal(str(periods_per_year)))
        return period_imputed
