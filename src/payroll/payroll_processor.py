"""
payroll_processor.py
Core Workday Payroll Processing Engine.

Orchestrates the full payroll run: fetches employee data from Workday,
calculates gross pay, applies taxes and deductions, and produces net pay
results ready for payment distribution.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Dict, Optional

from src.integrations.workday_api import WorkdayAPIClient, WorkdayAPIError
from src.payroll.compensation_calculator import CompensationCalculator, PayPeriod
from src.tax.federal_tax import FederalTaxCalculator
from src.tax.state_tax import StateTaxCalculator
from src.deductions.benefits_deduction import BenefitsDeductionCalculator
from src.deductions.retirement_deduction import RetirementDeductionCalculator

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class EmployeePayrollInput:
    """All data needed to compute payroll for one employee."""
    worker_id: str
    full_name: str
    pay_group: str
    pay_frequency: str           # WEEKLY | BIWEEKLY | SEMIMONTHLY | MONTHLY
    annual_salary: Decimal       # or 0 for hourly employees
    hourly_rate: Decimal         # or 0 for salaried
    hours_worked: Decimal        # regular hours in the period
    overtime_hours: Decimal
    bonus_amount: Decimal
    commission_amount: Decimal
    filing_status: str           # SINGLE | MARRIED | HEAD_OF_HOUSEHOLD
    federal_allowances: int
    state_code: str              # e.g. "CA", "TX", "NY"
    state_allowances: int
    additional_federal_withholding: Decimal
    additional_state_withholding: Decimal
    benefits_elections: List[Dict]  # from Workday deductions
    retirement_elections: List[Dict]
    garnishments: List[Dict]
    ytd_gross: Decimal = Decimal("0")
    ytd_federal_tax: Decimal = Decimal("0")
    ytd_state_tax: Decimal = Decimal("0")
    ytd_social_security: Decimal = Decimal("0")
    ytd_medicare: Decimal = Decimal("0")


@dataclass
class PayrollLineItem:
    """A single earning or deduction line on a pay slip."""
    code: str
    description: str
    amount: Decimal
    is_pretax: bool = False
    is_employer_contribution: bool = False


@dataclass
class EmployeePayrollResult:
    """Complete payroll calculation result for one employee."""
    worker_id: str
    full_name: str
    period_start: date
    period_end: date
    pay_date: date

    # Earnings
    regular_pay: Decimal = Decimal("0")
    overtime_pay: Decimal = Decimal("0")
    bonus_pay: Decimal = Decimal("0")
    commission_pay: Decimal = Decimal("0")
    gross_pay: Decimal = Decimal("0")

    # Taxes
    federal_income_tax: Decimal = Decimal("0")
    social_security_tax: Decimal = Decimal("0")
    medicare_tax: Decimal = Decimal("0")
    state_income_tax: Decimal = Decimal("0")
    local_tax: Decimal = Decimal("0")
    total_taxes: Decimal = Decimal("0")

    # Deductions
    pretax_deductions: Decimal = Decimal("0")
    posttax_deductions: Decimal = Decimal("0")
    retirement_pretax: Decimal = Decimal("0")
    retirement_roth: Decimal = Decimal("0")
    garnishments: Decimal = Decimal("0")
    total_deductions: Decimal = Decimal("0")

    # Net
    net_pay: Decimal = Decimal("0")

    # Employer contributions (informational)
    employer_social_security: Decimal = Decimal("0")
    employer_medicare: Decimal = Decimal("0")
    employer_benefits_contribution: Decimal = Decimal("0")

    # Detail lines
    line_items: List[PayrollLineItem] = field(default_factory=list)

    # Status
    status: str = "CALCULATED"   # CALCULATED | ERROR | VOIDED
    error_message: str = ""


@dataclass
class PayrollRunSummary:
    """Aggregate results for an entire payroll run."""
    run_id: str
    pay_group: str
    period_start: date
    period_end: date
    pay_date: date
    employee_count: int = 0
    total_gross: Decimal = Decimal("0")
    total_taxes: Decimal = Decimal("0")
    total_deductions: Decimal = Decimal("0")
    total_net: Decimal = Decimal("0")
    total_employer_ss: Decimal = Decimal("0")
    total_employer_medicare: Decimal = Decimal("0")
    total_employer_benefits: Decimal = Decimal("0")
    errors: List[str] = field(default_factory=list)
    results: List[EmployeePayrollResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main processor
# ---------------------------------------------------------------------------

class PayrollProcessor:
    """
    Workday Payroll Processing Engine.

    Fetches live data from Workday, runs calculations for each employee,
    and produces a PayrollRunSummary that can be submitted back to Workday
    or used to generate pay slips and reports.

    Usage:
        processor = PayrollProcessor(workday_client)
        summary = processor.process_payroll_run(
            run_id="PAY-2025-001",
            pay_group="BI-WEEKLY-US",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 14),
            pay_date=date(2025, 1, 17)
        )
    """

    # FICA rates (2025)
    SOCIAL_SECURITY_RATE = Decimal("0.062")
    MEDICARE_RATE = Decimal("0.0145")
    ADDITIONAL_MEDICARE_RATE = Decimal("0.009")
    ADDITIONAL_MEDICARE_THRESHOLD = Decimal("200000")
    SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")  # 2025 wage base

    def __init__(self, client: WorkdayAPIClient):
        self.client = client
        self.comp_calc = CompensationCalculator()
        self.federal_tax = FederalTaxCalculator()
        self.state_tax = StateTaxCalculator()
        self.benefits_calc = BenefitsDeductionCalculator()
        self.retirement_calc = RetirementDeductionCalculator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_payroll_run(
        self,
        run_id: str,
        pay_group: str,
        period_start: date,
        period_end: date,
        pay_date: date,
        worker_ids: Optional[List[str]] = None,
    ) -> PayrollRunSummary:
        """
        Execute a full payroll run.

        Args:
            run_id:       Workday payroll run identifier.
            pay_group:    Workday pay group ID.
            period_start: Start of the pay period.
            period_end:   End of the pay period.
            pay_date:     Date employees will be paid.
            worker_ids:   Optional list to process only specific workers.

        Returns:
            PayrollRunSummary with all employee results and aggregates.
        """
        logger.info("Starting payroll run %s | %s -> %s | pay date %s",
                    run_id, period_start, period_end, pay_date)

        summary = PayrollRunSummary(
            run_id=run_id,
            pay_group=pay_group,
            period_start=period_start,
            period_end=period_end,
            pay_date=pay_date,
        )

        # 1. Fetch employee payroll inputs from Workday
        employees = self._fetch_employee_inputs(pay_group, period_start, period_end, worker_ids)
        logger.info("Fetched %d employees for processing", len(employees))

        # 2. Calculate payroll for each employee
        for emp in employees:
            try:
                result = self._calculate_employee_payroll(emp, period_start, period_end, pay_date)
                summary.results.append(result)
                summary.employee_count += 1
                summary.total_gross += result.gross_pay
                summary.total_taxes += result.total_taxes
                summary.total_deductions += result.total_deductions
                summary.total_net += result.net_pay
                summary.total_employer_ss += result.employer_social_security
                summary.total_employer_medicare += result.employer_medicare
                summary.total_employer_benefits += result.employer_benefits_contribution
            except Exception as exc:
                msg = f"Error processing worker {emp.worker_id} ({emp.full_name}): {exc}"
                logger.error(msg, exc_info=True)
                summary.errors.append(msg)
                err_result = EmployeePayrollResult(
                    worker_id=emp.worker_id,
                    full_name=emp.full_name,
                    period_start=period_start,
                    period_end=period_end,
                    pay_date=pay_date,
                    status="ERROR",
                    error_message=str(exc),
                )
                summary.results.append(err_result)

        logger.info(
            "Payroll run %s complete | %d employees | gross=%s | net=%s | errors=%d",
            run_id, summary.employee_count, summary.total_gross,
            summary.total_net, len(summary.errors)
        )
        return summary

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_employee_inputs(
        self,
        pay_group: str,
        period_start: date,
        period_end: date,
        worker_ids: Optional[List[str]] = None,
    ) -> List[EmployeePayrollInput]:
        """Fetch all necessary employee data from Workday."""
        workers = self.client.get_all_workers(as_of_date=str(period_end))
        if worker_ids:
            workers = [w for w in workers if w.get("workerId") in worker_ids]

        inputs = []
        for worker in workers:
            wid = worker.get("workerId")
            try:
                comp = self.client.get_worker_compensation(wid)
                deductions = self.client.get_worker_deductions(wid)
                tax_elections = self.client.get_worker_tax_elections(wid)
                inp = self._map_workday_data(worker, comp, deductions, tax_elections, period_start, period_end)
                inputs.append(inp)
            except WorkdayAPIError as e:
                logger.warning("Could not fetch data for worker %s: %s", wid, e)
        return inputs

    def _map_workday_data(
        self, worker: Dict, comp: Dict, deductions: List[Dict],
        tax_elections: Dict, period_start: date, period_end: date
    ) -> EmployeePayrollInput:
        """Map raw Workday API data to EmployeePayrollInput."""
        pay_freq = comp.get("payFrequency", {}).get("id", "BIWEEKLY")
        period = PayPeriod(pay_freq, period_start, period_end)

        annual_salary = Decimal(str(comp.get("annualSalary", {}).get("amount", 0)))
        hourly_rate = Decimal(str(comp.get("hourlyRate", {}).get("amount", 0)))

        hours = comp.get("scheduledHours", {})
        hours_worked = Decimal(str(hours.get("regular", 80)))
        overtime_hours = Decimal(str(hours.get("overtime", 0)))

        bonuses = [e for e in deductions if e.get("earningType") == "BONUS"]
        commissions = [e for e in deductions if e.get("earningType") == "COMMISSION"]
        benefits = [d for d in deductions if d.get("deductionCategory") == "BENEFITS"]
        retirement = [d for d in deductions if d.get("deductionCategory") == "RETIREMENT"]
        garnishments = [d for d in deductions if d.get("deductionCategory") == "GARNISHMENT"]

        fed = tax_elections.get("federal", {})
        state_e = tax_elections.get("state", {})

        ytd = comp.get("ytdTotals", {})

        return EmployeePayrollInput(
            worker_id=worker.get("workerId", ""),
            full_name=f"{worker.get('firstName','')} {worker.get('lastName','')}".strip(),
            pay_group=worker.get("payGroup", {}).get("id", ""),
            pay_frequency=pay_freq,
            annual_salary=annual_salary,
            hourly_rate=hourly_rate,
            hours_worked=hours_worked,
            overtime_hours=overtime_hours,
            bonus_amount=Decimal(str(sum(b.get("amount", 0) for b in bonuses))),
            commission_amount=Decimal(str(sum(c.get("amount", 0) for c in commissions))),
            filing_status=fed.get("filingStatus", "SINGLE"),
            federal_allowances=int(fed.get("allowances", 0)),
            state_code=state_e.get("stateCode", "CA"),
            state_allowances=int(state_e.get("allowances", 0)),
            additional_federal_withholding=Decimal(str(fed.get("additionalWithholding", 0))),
            additional_state_withholding=Decimal(str(state_e.get("additionalWithholding", 0))),
            benefits_elections=benefits,
            retirement_elections=retirement,
            garnishments=garnishments,
            ytd_gross=Decimal(str(ytd.get("grossPay", 0))),
            ytd_federal_tax=Decimal(str(ytd.get("federalTax", 0))),
            ytd_state_tax=Decimal(str(ytd.get("stateTax", 0))),
            ytd_social_security=Decimal(str(ytd.get("socialSecurity", 0))),
            ytd_medicare=Decimal(str(ytd.get("medicare", 0))),
        )

    # ------------------------------------------------------------------
    # Calculation pipeline
    # ------------------------------------------------------------------

    def _calculate_employee_payroll(
        self, emp: EmployeePayrollInput,
        period_start: date, period_end: date, pay_date: date
    ) -> EmployeePayrollResult:
        """Run the full payroll calculation pipeline for one employee."""
        result = EmployeePayrollResult(
            worker_id=emp.worker_id,
            full_name=emp.full_name,
            period_start=period_start,
            period_end=period_end,
            pay_date=pay_date,
        )
        period = PayPeriod(emp.pay_frequency, period_start, period_end)

        # Step 1: Gross pay
        result.regular_pay, result.overtime_pay = self.comp_calc.calculate_gross_pay(
            annual_salary=emp.annual_salary,
            hourly_rate=emp.hourly_rate,
            hours_worked=emp.hours_worked,
            overtime_hours=emp.overtime_hours,
            pay_period=period,
        )
        result.bonus_pay = _round(emp.bonus_amount)
        result.commission_pay = _round(emp.commission_amount)
        result.gross_pay = _round(
            result.regular_pay + result.overtime_pay
            + result.bonus_pay + result.commission_pay
        )

        # Step 2: Pre-tax deductions (reduce taxable wages)
        retirement = self.retirement_calc.calculate(emp.retirement_elections, result.gross_pay)
        result.retirement_pretax = _round(retirement.pretax_401k)
        result.retirement_roth = _round(retirement.roth_401k)
        benefits = self.benefits_calc.calculate(emp.benefits_elections)
        result.pretax_deductions = _round(benefits.pretax_total)

        taxable_wages = _round(
            result.gross_pay - result.retirement_pretax - result.pretax_deductions
        )

        # Step 3: FICA taxes
        result.social_security_tax, result.employer_social_security = (
            self._calculate_social_security(taxable_wages, emp.ytd_gross)
        )
        result.medicare_tax, result.employer_medicare = (
            self._calculate_medicare(taxable_wages, emp.ytd_gross)
        )

        # Step 4: Federal income tax
        result.federal_income_tax = self.federal_tax.calculate(
            taxable_wages=taxable_wages,
            pay_frequency=emp.pay_frequency,
            filing_status=emp.filing_status,
            allowances=emp.federal_allowances,
            additional_withholding=emp.additional_federal_withholding,
        )

        # Step 5: State income tax
        result.state_income_tax = self.state_tax.calculate(
            taxable_wages=taxable_wages,
            state_code=emp.state_code,
            pay_frequency=emp.pay_frequency,
            filing_status=emp.filing_status,
            allowances=emp.state_allowances,
            additional_withholding=emp.additional_state_withholding,
        )

        # Step 6: Post-tax deductions
        result.posttax_deductions = _round(benefits.posttax_total)
        result.garnishments = _round(
            Decimal(str(sum(g.get("amount", 0) for g in emp.garnishments)))
        )
        result.employer_benefits_contribution = _round(benefits.employer_contribution)

        # Step 7: Totals
        result.total_taxes = _round(
            result.federal_income_tax + result.social_security_tax
            + result.medicare_tax + result.state_income_tax + result.local_tax
        )
        result.total_deductions = _round(
            result.pretax_deductions + result.posttax_deductions
            + result.retirement_pretax + result.retirement_roth
            + result.garnishments + result.total_taxes
        )
        result.net_pay = _round(result.gross_pay - result.total_deductions)

        # Step 8: Build line items for pay slip
        result.line_items = self._build_line_items(emp, result)

        return result

    def _calculate_social_security(
        self, taxable_wages: Decimal, ytd_gross: Decimal
    ):
        """Calculate employee and employer Social Security tax with wage base cap."""
        remaining_base = max(Decimal("0"), self.SOCIAL_SECURITY_WAGE_BASE - ytd_gross)
        ss_wages = min(taxable_wages, remaining_base)
        employee_ss = _round(ss_wages * self.SOCIAL_SECURITY_RATE)
        employer_ss = _round(ss_wages * self.SOCIAL_SECURITY_RATE)
        return employee_ss, employer_ss

    def _calculate_medicare(
        self, taxable_wages: Decimal, ytd_gross: Decimal
    ):
        """Calculate employee and employer Medicare tax including Additional Medicare Tax."""
        employee_medicare = _round(taxable_wages * self.MEDICARE_RATE)
        employer_medicare = _round(taxable_wages * self.MEDICARE_RATE)
        # Additional Medicare Tax (0.9%) for wages over threshold
        if ytd_gross + taxable_wages > self.ADDITIONAL_MEDICARE_THRESHOLD:
            excess = (ytd_gross + taxable_wages) - self.ADDITIONAL_MEDICARE_THRESHOLD
            excess = min(excess, taxable_wages)
            employee_medicare += _round(excess * self.ADDITIONAL_MEDICARE_RATE)
        return employee_medicare, employer_medicare

    def _build_line_items(
        self, emp: EmployeePayrollInput, result: EmployeePayrollResult
    ) -> List[PayrollLineItem]:
        """Build the detailed line items list for a pay slip."""
        items = []
        if result.regular_pay:
            items.append(PayrollLineItem("REG", "Regular Pay", result.regular_pay))
        if result.overtime_pay:
            items.append(PayrollLineItem("OT", "Overtime Pay", result.overtime_pay))
        if result.bonus_pay:
            items.append(PayrollLineItem("BONUS", "Bonus", result.bonus_pay))
        if result.commission_pay:
            items.append(PayrollLineItem("COMM", "Commission", result.commission_pay))
        if result.retirement_pretax:
            items.append(PayrollLineItem("401K", "401(k) Pre-Tax", -result.retirement_pretax, is_pretax=True))
        if result.retirement_roth:
            items.append(PayrollLineItem("ROTH", "Roth 401(k)", -result.retirement_roth))
        if result.pretax_deductions:
            items.append(PayrollLineItem("BENEFITS", "Benefits (Pre-Tax)", -result.pretax_deductions, is_pretax=True))
        if result.federal_income_tax:
            items.append(PayrollLineItem("FED_TAX", "Federal Income Tax", -result.federal_income_tax))
        if result.social_security_tax:
            items.append(PayrollLineItem("SS_TAX", "Social Security Tax", -result.social_security_tax))
        if result.medicare_tax:
            items.append(PayrollLineItem("MED_TAX", "Medicare Tax", -result.medicare_tax))
        if result.state_income_tax:
            items.append(PayrollLineItem("STATE_TAX", f"{emp.state_code} State Tax", -result.state_income_tax))
        if result.posttax_deductions:
            items.append(PayrollLineItem("POST_DED", "Post-Tax Deductions", -result.posttax_deductions))
        if result.garnishments:
            items.append(PayrollLineItem("GARN", "Garnishments", -result.garnishments))
        return items
