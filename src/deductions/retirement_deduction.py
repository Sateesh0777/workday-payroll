"""
retirement_deduction.py
Retirement Plan Deduction Calculator.

Handles 401(k), 403(b), Roth 401(k), employer matching, catch-up
contributions, and other retirement-related payroll deductions.
Enforces 2025 IRS contribution limits.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# 2025 IRS Retirement Contribution Limits
# ---------------------------------------------------------------------------
IRS_RETIREMENT_LIMITS_2025 = {
    "401K_EMPLOYEE":        Decimal("23500"),   # 401(k) / 403(b) employee elective
    "401K_CATCHUP_50":      Decimal("7500"),    # Catch-up for age 50-59 and 64+
    "401K_CATCHUP_60_63":   Decimal("11250"),   # SECURE 2.0 super catch-up age 60-63
    "401K_TOTAL":           Decimal("70000"),   # Combined employee + employer annual max
    "IRA_EMPLOYEE":         Decimal("7000"),    # Traditional / Roth IRA
    "IRA_CATCHUP":          Decimal("1000"),    # IRA catch-up age 50+
    "SIMPLE_EMPLOYEE":      Decimal("16500"),   # SIMPLE IRA employee
    "SIMPLE_CATCHUP":       Decimal("3500"),    # SIMPLE IRA catch-up age 50+
}

# Retirement plan types and their pre-tax status
PLAN_TAX_TREATMENT = {
    "401K":           {"pretax": True,  "roth": False, "limit_key": "401K_EMPLOYEE"},
    "ROTH_401K":      {"pretax": False, "roth": True,  "limit_key": "401K_EMPLOYEE"},
    "403B":           {"pretax": True,  "roth": False, "limit_key": "401K_EMPLOYEE"},
    "ROTH_403B":      {"pretax": False, "roth": True,  "limit_key": "401K_EMPLOYEE"},
    "457B":           {"pretax": True,  "roth": False, "limit_key": "401K_EMPLOYEE"},
    "SIMPLE_IRA":     {"pretax": True,  "roth": False, "limit_key": "SIMPLE_EMPLOYEE"},
    "TRADITIONAL_IRA":{"pretax": True,  "roth": False, "limit_key": "IRA_EMPLOYEE"},
    "ROTH_IRA":       {"pretax": False, "roth": True,  "limit_key": "IRA_EMPLOYEE"},
}


@dataclass
class RetirementElection:
    """A single retirement plan election."""
    plan_type: str              # e.g. "401K", "ROTH_401K"
    plan_name: str
    election_type: str          # PERCENTAGE | FLAT_AMOUNT
    election_value: Decimal     # Percent (e.g. 0.06 for 6%) or flat amount
    employee_age: int           # For catch-up contribution eligibility
    ytd_employee: Decimal = Decimal("0")
    ytd_employer: Decimal = Decimal("0")
    employer_match_percent: Decimal = Decimal("0")   # e.g. 0.50 for 50% match
    employer_match_cap: Decimal = Decimal("0")        # % of comp (e.g. 0.06 for up to 6%)
    vesting_percent: Decimal = Decimal("1.0")         # 1.0 = 100% vested


@dataclass
class RetirementDeductionResult:
    """Retirement deduction result for one pay period."""
    pretax_401k: Decimal = Decimal("0")
    roth_401k: Decimal = Decimal("0")
    employer_match: Decimal = Decimal("0")
    total_employee: Decimal = Decimal("0")
    total_combined: Decimal = Decimal("0")
    line_items: List[Dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    limit_hits: List[str] = field(default_factory=list)


class RetirementDeductionCalculator:
    """
    Retirement Plan Deduction Calculator (2025 IRS limits).

    Supports:
    - 401(k), 403(b), 457(b), SIMPLE IRA, Traditional/Roth IRA
    - Both percentage-of-gross and flat-amount elections
    - Catch-up contributions (age 50+ and SECURE 2.0 age 60-63)
    - Employer matching with caps
    - Combined limit enforcement ($70,000 total 2025)

    Usage:
        calc = RetirementDeductionCalculator()
        result = calc.calculate(retirement_elections, gross_pay)
    """

    def calculate(
        self,
        elections: List[Dict],
        gross_pay: Decimal,
    ) -> RetirementDeductionResult:
        """
        Calculate retirement deductions for a pay period.

        Args:
            elections: List of retirement election dicts from Workday.
                       Keys: planType, planName, electionType, electionValue,
                             employeeAge, ytdEmployee, ytdEmployer,
                             employerMatchPercent, employerMatchCap, vestingPercent
            gross_pay: Gross pay before any deductions for this period.

        Returns:
            RetirementDeductionResult with all component amounts.
        """
        result = RetirementDeductionResult()

        for election in elections:
            plan_type = election.get("planType", "401K").upper()
            plan_name = election.get("planName", plan_type)
            election_type = election.get("electionType", "PERCENTAGE").upper()
            election_value = Decimal(str(election.get("electionValue", 0)))
            employee_age = int(election.get("employeeAge", 30))
            ytd_employee = Decimal(str(election.get("ytdEmployee", 0)))
            ytd_employer = Decimal(str(election.get("ytdEmployer", 0)))
            match_pct = Decimal(str(election.get("employerMatchPercent", 0)))
            match_cap = Decimal(str(election.get("employerMatchCap", 0)))
            vesting = Decimal(str(election.get("vestingPercent", 1.0)))

            # Calculate raw employee contribution for the period
            if election_type == "PERCENTAGE":
                employee_contrib = _round(gross_pay * election_value)
            else:
                employee_contrib = _round(election_value)

            # Get the annual limit for this plan type
            plan_info = PLAN_TAX_TREATMENT.get(plan_type, PLAN_TAX_TREATMENT["401K"])
            limit_key = plan_info["limit_key"]
            base_limit = IRS_RETIREMENT_LIMITS_2025.get(limit_key, Decimal("23500"))

            # Add catch-up if eligible
            catch_up = self._get_catchup_limit(plan_type, employee_age)
            annual_limit = base_limit + catch_up

            # Cap at remaining annual limit
            remaining = max(Decimal("0"), annual_limit - ytd_employee)
            if employee_contrib > remaining:
                result.warnings.append(
                    f"{plan_name}: contribution {employee_contrib} capped at "
                    f"remaining limit {remaining} (YTD: {ytd_employee}, Limit: {annual_limit})"
                )
                result.limit_hits.append(plan_name)
                employee_contrib = remaining

            # Calculate employer match
            employer_contrib = Decimal("0")
            if match_pct > 0:
                if election_type == "PERCENTAGE":
                    eligible_pct = min(election_value, match_cap) if match_cap > 0 else election_value
                    employer_contrib = _round(gross_pay * eligible_pct * match_pct * vesting)
                else:
                    # Flat amount match
                    employer_contrib = _round(employee_contrib * match_pct * vesting)

                # Cap employer match at remaining combined limit
                combined_ytd = ytd_employee + ytd_employer
                combined_limit = IRS_RETIREMENT_LIMITS_2025["401K_TOTAL"]
                combined_remaining = max(Decimal("0"), combined_limit - combined_ytd - employee_contrib)
                employer_contrib = min(employer_contrib, combined_remaining)

            # Classify as pre-tax or Roth
            is_pretax = plan_info["pretax"]
            is_roth = plan_info["roth"]

            if is_pretax:
                result.pretax_401k += employee_contrib
            elif is_roth:
                result.roth_401k += employee_contrib

            result.employer_match += employer_contrib

            result.line_items.append({
                "planType": plan_type,
                "planName": plan_name,
                "employeeContribution": _round(employee_contrib),
                "employerContribution": _round(employer_contrib),
                "isPretax": is_pretax,
                "isRoth": is_roth,
                "catchUpEligible": catch_up > 0,
                "ytdEmployee": _round(ytd_employee + employee_contrib),
            })

        result.pretax_401k = _round(result.pretax_401k)
        result.roth_401k = _round(result.roth_401k)
        result.employer_match = _round(result.employer_match)
        result.total_employee = _round(result.pretax_401k + result.roth_401k)
        result.total_combined = _round(result.total_employee + result.employer_match)
        return result

    def _get_catchup_limit(self, plan_type: str, age: int) -> Decimal:
        """Return applicable catch-up contribution limit based on age and plan type."""
        if plan_type in ("401K", "ROTH_401K", "403B", "ROTH_403B"):
            if 60 <= age <= 63:
                return IRS_RETIREMENT_LIMITS_2025["401K_CATCHUP_60_63"]
            elif age >= 50:
                return IRS_RETIREMENT_LIMITS_2025["401K_CATCHUP_50"]
        elif plan_type == "SIMPLE_IRA":
            if age >= 50:
                return IRS_RETIREMENT_LIMITS_2025["SIMPLE_CATCHUP"]
        elif plan_type in ("TRADITIONAL_IRA", "ROTH_IRA"):
            if age >= 50:
                return IRS_RETIREMENT_LIMITS_2025["IRA_CATCHUP"]
        return Decimal("0")

    def project_annual_contribution(
        self,
        gross_pay_per_period: Decimal,
        election_value: Decimal,
        election_type: str,
        periods_remaining: int,
        plan_type: str = "401K",
        employee_age: int = 40,
    ) -> Dict:
        """
        Project total annual contribution and whether limit will be hit.
        Useful for generating employee-facing payroll summaries.
        """
        if election_type.upper() == "PERCENTAGE":
            per_period = _round(gross_pay_per_period * election_value)
        else:
            per_period = _round(election_value)

        projected_total = _round(per_period * Decimal(str(periods_remaining)))
        plan_info = PLAN_TAX_TREATMENT.get(plan_type.upper(), PLAN_TAX_TREATMENT["401K"])
        limit_key = plan_info["limit_key"]
        base_limit = IRS_RETIREMENT_LIMITS_2025.get(limit_key, Decimal("23500"))
        catch_up = self._get_catchup_limit(plan_type, employee_age)
        annual_limit = base_limit + catch_up

        return {
            "perPeriodContribution": per_period,
            "projectedAnnualTotal": projected_total,
            "annualLimit": annual_limit,
            "willHitLimit": projected_total > annual_limit,
            "periodsUntilLimit": int(annual_limit / per_period) if per_period > 0 else None,
        }
