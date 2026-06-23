"""
tax_reports.py
Payroll Tax Filing Reports.

Generates IRS Form 941 (Employer's Quarterly Federal Tax Return) and
Form 940 (Federal Unemployment Tax) summary data from payroll run history.
Also produces state unemployment (SUTA) and local tax liability reports.
"""

import json
import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional

from src.payroll.payroll_processor import PayrollRunSummary, EmployeePayrollResult

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# FUTA / SUTA constants (2025)
# ---------------------------------------------------------------------------

FUTA_RATE = Decimal("0.06")          # 6.0% gross FUTA rate
FUTA_CREDIT_RATE = Decimal("0.054")  # 5.4% credit for states paying SUTA on time
FUTA_NET_RATE = Decimal("0.006")     # 0.6% effective net rate after credit
FUTA_WAGE_BASE = Decimal("7000")     # Per-employee annual wage base

SOCIAL_SECURITY_RATE = Decimal("0.062")   # Employee + Employer each
MEDICARE_RATE = Decimal("0.0145")         # Employee + Employer each


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Form941LineItems:
    """
    Key line items for IRS Form 941 (Quarterly Federal Tax Return).
    Line numbers correspond to the 2025 Form 941 layout.
    """
    quarter: int                          # 1-4
    year: int
    employer_ein: str = ""
    employer_name: str = ""

    # Line 1: Number of employees who received wages
    employee_count: int = 0

    # Line 2: Wages, tips, and other compensation
    total_wages: Decimal = Decimal("0")

    # Line 3: Federal income tax withheld
    federal_income_tax_withheld: Decimal = Decimal("0")

    # Line 5a: Taxable Social Security wages (employee + employer)
    taxable_ss_wages: Decimal = Decimal("0")
    ss_tax_employee: Decimal = Decimal("0")
    ss_tax_employer: Decimal = Decimal("0")

    # Line 5c: Taxable Medicare wages
    taxable_medicare_wages: Decimal = Decimal("0")
    medicare_tax_employee: Decimal = Decimal("0")
    medicare_tax_employer: Decimal = Decimal("0")

    # Line 5d: Additional Medicare Tax withheld
    additional_medicare_tax: Decimal = Decimal("0")

    # Line 6: Total taxes before adjustments
    total_taxes_before_adjustments: Decimal = Decimal("0")

    # Line 12: Total taxes after adjustments
    total_taxes: Decimal = Decimal("0")

    # Deposit liability
    total_deposits: Decimal = Decimal("0")
    balance_due: Decimal = Decimal("0")


@dataclass
class Form940Summary:
    """Summary data for IRS Form 940 (Annual FUTA Tax Return)."""
    year: int
    employer_ein: str = ""
    employer_name: str = ""
    total_payments_to_employees: Decimal = Decimal("0")
    exempt_payments: Decimal = Decimal("0")
    futa_taxable_wages: Decimal = Decimal("0")
    futa_tax_before_adjustments: Decimal = Decimal("0")
    futa_credit_reduction: Decimal = Decimal("0")
    total_futa_tax: Decimal = Decimal("0")
    total_futa_deposits: Decimal = Decimal("0")
    balance_due: Decimal = Decimal("0")


@dataclass
class TaxLiabilityByPeriod:
    """Tax liability breakdown for a single payroll period."""
    period_start: date
    period_end: date
    pay_date: date
    employee_federal_income_tax: Decimal = Decimal("0")
    employee_social_security: Decimal = Decimal("0")
    employer_social_security: Decimal = Decimal("0")
    employee_medicare: Decimal = Decimal("0")
    employer_medicare: Decimal = Decimal("0")
    additional_medicare: Decimal = Decimal("0")
    total_941_liability: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Tax Report Generator
# ---------------------------------------------------------------------------

class TaxReportGenerator:
    """
    Generates IRS Form 941, Form 940, and supporting tax liability reports
    from accumulated payroll run data.

    Usage::

        generator = TaxReportGenerator(
            employer_ein="12-3456789",
            employer_name="Acme Corp",
        )
        for run_summary in quarterly_runs:
            generator.add_payroll_run(run_summary)

        form_941 = generator.generate_form_941(quarter=1, year=2025)
        print(generator.form_941_to_text(form_941))
        print(generator.form_941_to_json(form_941))
    """

    def __init__(self, employer_ein: str = "", employer_name: str = ""):
        self.employer_ein = employer_ein
        self.employer_name = employer_name
        self._runs: List[PayrollRunSummary] = []

    def add_payroll_run(self, run: PayrollRunSummary) -> None:
        """Register a completed payroll run for reporting."""
        self._runs.append(run)

    def add_payroll_runs(self, runs: List[PayrollRunSummary]) -> None:
        """Register multiple payroll runs at once."""
        self._runs.extend(runs)

    # ------------------------------------------------------------------
    # Form 941
    # ------------------------------------------------------------------

    def generate_form_941(self, quarter: int, year: int) -> Form941LineItems:
        """
        Build Form 941 line items for a given quarter.

        Args:
            quarter: Calendar quarter (1=Jan-Mar, 2=Apr-Jun, 3=Jul-Sep, 4=Oct-Dec).
            year:    Calendar year.

        Returns:
            Form941LineItems populated from all matching payroll runs.
        """
        if quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1-4, got {quarter}")

        quarter_months = {
            1: (1, 2, 3),
            2: (4, 5, 6),
            3: (7, 8, 9),
            4: (10, 11, 12),
        }
        months = quarter_months[quarter]

        form = Form941LineItems(
            quarter=quarter,
            year=year,
            employer_ein=self.employer_ein,
            employer_name=self.employer_name,
        )

        worker_ids_seen: set = set()

        for run in self._runs:
            if run.pay_date.year != year or run.pay_date.month not in months:
                continue

            for emp in run.results:
                if emp.status != "CALCULATED":
                    continue

                worker_ids_seen.add(emp.worker_id)
                form.total_wages += emp.gross_pay
                form.federal_income_tax_withheld += emp.federal_income_tax
                form.taxable_ss_wages += emp.gross_pay
                form.ss_tax_employee += emp.social_security_tax
                form.ss_tax_employer += emp.employer_social_security
                form.taxable_medicare_wages += emp.gross_pay
                form.medicare_tax_employee += emp.medicare_tax
                form.medicare_tax_employer += emp.employer_medicare

        form.employee_count = len(worker_ids_seen)
        form.total_wages = _round(form.total_wages)
        form.federal_income_tax_withheld = _round(form.federal_income_tax_withheld)
        form.taxable_ss_wages = _round(form.taxable_ss_wages)
        form.ss_tax_employee = _round(form.ss_tax_employee)
        form.ss_tax_employer = _round(form.ss_tax_employer)
        form.taxable_medicare_wages = _round(form.taxable_medicare_wages)
        form.medicare_tax_employee = _round(form.medicare_tax_employee)
        form.medicare_tax_employer = _round(form.medicare_tax_employer)

        form.total_taxes_before_adjustments = _round(
            form.federal_income_tax_withheld
            + form.ss_tax_employee + form.ss_tax_employer
            + form.medicare_tax_employee + form.medicare_tax_employer
            + form.additional_medicare_tax
        )
        form.total_taxes = form.total_taxes_before_adjustments
        form.balance_due = _round(form.total_taxes - form.total_deposits)

        logger.info(
            "Form 941 Q%d %d: %d employees, wages=%s, total_tax=%s",
            quarter, year, form.employee_count, form.total_wages, form.total_taxes,
        )
        return form

    def form_941_to_text(self, form: Form941LineItems) -> str:
        """Render Form 941 data as a readable text summary."""
        q_names = {1: "January-March", 2: "April-June",
                   3: "July-September", 4: "October-December"}
        sep = "=" * 65
        dash = "-" * 65
        lines = [
            sep,
            f"  FORM 941 - Employer's Quarterly Federal Tax Return",
            f"  Quarter: Q{form.quarter} ({q_names[form.quarter]}) {form.year}",
            f"  EIN: {form.employer_ein}   Employer: {form.employer_name}",
            sep,
            f"  Line 1 - Employees paid:                {form.employee_count:>12,}",
            f"  Line 2 - Total wages:                   ${form.total_wages:>12,.2f}",
            f"  Line 3 - Federal income tax withheld:   ${form.federal_income_tax_withheld:>12,.2f}",
            dash,
            f"  Line 5a - SS wages:                     ${form.taxable_ss_wages:>12,.2f}",
            f"         - SS tax (employee):              ${form.ss_tax_employee:>12,.2f}",
            f"         - SS tax (employer):              ${form.ss_tax_employer:>12,.2f}",
            f"  Line 5c - Medicare wages:               ${form.taxable_medicare_wages:>12,.2f}",
            f"         - Medicare tax (employee):        ${form.medicare_tax_employee:>12,.2f}",
            f"         - Medicare tax (employer):        ${form.medicare_tax_employer:>12,.2f}",
            f"  Line 5d - Additional Medicare:          ${form.additional_medicare_tax:>12,.2f}",
            dash,
            f"  Line 12 - TOTAL TAX LIABILITY:          ${form.total_taxes:>12,.2f}",
            f"          - Total deposits made:           ${form.total_deposits:>12,.2f}",
            f"          - Balance due / (overpayment):  ${form.balance_due:>12,.2f}",
            sep,
        ]
        return "\n".join(lines)

    def form_941_to_json(self, form: Form941LineItems) -> str:
        """Serialize Form 941 data to JSON."""
        data = {
            "formType": "941",
            "quarter": form.quarter,
            "year": form.year,
            "employerEIN": form.employer_ein,
            "employerName": form.employer_name,
            "line1_employeeCount": form.employee_count,
            "line2_totalWages": str(form.total_wages),
            "line3_federalIncomeTaxWithheld": str(form.federal_income_tax_withheld),
            "line5a_taxableSSwages": str(form.taxable_ss_wages),
            "line5a_ssEmployeeTax": str(form.ss_tax_employee),
            "line5a_ssEmployerTax": str(form.ss_tax_employer),
            "line5c_taxableMedicareWages": str(form.taxable_medicare_wages),
            "line5c_medicareEmployeeTax": str(form.medicare_tax_employee),
            "line5c_medicareEmployerTax": str(form.medicare_tax_employer),
            "line5d_additionalMedicareTax": str(form.additional_medicare_tax),
            "line12_totalTaxes": str(form.total_taxes),
            "totalDeposits": str(form.total_deposits),
            "balanceDue": str(form.balance_due),
        }
        return json.dumps(data, indent=2)

    # ------------------------------------------------------------------
    # Form 940
    # ------------------------------------------------------------------

    def generate_form_940(self, year: int) -> Form940Summary:
        """
        Build Form 940 (Annual FUTA Tax Return) for a given year.

        FUTA is 6% on first $7,000 of each employee's wages, less
        5.4% credit for timely SUTA payments = 0.6% net.
        """
        form = Form940Summary(
            year=year,
            employer_ein=self.employer_ein,
            employer_name=self.employer_name,
        )

        # Track per-employee YTD gross to cap at FUTA wage base
        ytd_wages: Dict[str, Decimal] = {}

        for run in self._runs:
            if run.pay_date.year != year:
                continue
            for emp in run.results:
                if emp.status != "CALCULATED":
                    continue
                form.total_payments_to_employees += emp.gross_pay
                prev = ytd_wages.get(emp.worker_id, Decimal("0"))
                # Only the first $7,000 per employee is FUTA-taxable
                taxable = max(Decimal("0"),
                              min(emp.gross_pay, FUTA_WAGE_BASE - prev))
                ytd_wages[emp.worker_id] = prev + emp.gross_pay
                form.futa_taxable_wages += taxable

        form.total_payments_to_employees = _round(form.total_payments_to_employees)
        form.futa_taxable_wages = _round(form.futa_taxable_wages)
        form.futa_tax_before_adjustments = _round(form.futa_taxable_wages * FUTA_RATE)
        # Assume full 5.4% credit (employer paid SUTA on time)
        form.futa_credit_reduction = _round(form.futa_taxable_wages * FUTA_CREDIT_RATE)
        form.total_futa_tax = _round(form.futa_taxable_wages * FUTA_NET_RATE)
        form.balance_due = _round(form.total_futa_tax - form.total_futa_deposits)

        logger.info(
            "Form 940 %d: taxable wages=%s, FUTA tax=%s",
            year, form.futa_taxable_wages, form.total_futa_tax,
        )
        return form

    def form_940_to_text(self, form: Form940Summary) -> str:
        """Render Form 940 data as readable text."""
        sep = "=" * 65
        dash = "-" * 65
        lines = [
            sep,
            f"  FORM 940 - Employer's Annual FUTA Tax Return  ({form.year})",
            f"  EIN: {form.employer_ein}   Employer: {form.employer_name}",
            sep,
            f"  Total payments to employees:          ${form.total_payments_to_employees:>12,.2f}",
            f"  FUTA taxable wages (first $7,000):    ${form.futa_taxable_wages:>12,.2f}",
            dash,
            f"  FUTA tax before adjustments (6%):     ${form.futa_tax_before_adjustments:>12,.2f}",
            f"  SUTA credit reduction (5.4%):        -${form.futa_credit_reduction:>12,.2f}",
            f"  NET FUTA TAX (0.6%):                  ${form.total_futa_tax:>12,.2f}",
            dash,
            f"  Total FUTA deposits:                  ${form.total_futa_deposits:>12,.2f}",
            f"  Balance due / (overpayment):          ${form.balance_due:>12,.2f}",
            sep,
        ]
        return "\n".join(lines)

    def form_940_to_json(self, form: Form940Summary) -> str:
        """Serialize Form 940 data to JSON."""
        data = {
            "formType": "940",
            "year": form.year,
            "employerEIN": form.employer_ein,
            "employerName": form.employer_name,
            "totalPaymentsToEmployees": str(form.total_payments_to_employees),
            "futaTaxableWages": str(form.futa_taxable_wages),
            "futaTaxBeforeAdjustments": str(form.futa_tax_before_adjustments),
            "sutaCreditReduction": str(form.futa_credit_reduction),
            "totalFutaTax": str(form.total_futa_tax),
            "totalFutaDeposits": str(form.total_futa_deposits),
            "balanceDue": str(form.balance_due),
        }
        return json.dumps(data, indent=2)

    # ------------------------------------------------------------------
    # Period-by-period tax liability schedule
    # ------------------------------------------------------------------

    def generate_liability_schedule(
        self, year: int, quarter: Optional[int] = None
    ) -> List[TaxLiabilityByPeriod]:
        """
        Generate a period-by-period 941 tax deposit liability schedule.
        Useful for verifying semi-weekly or monthly deposit schedules.
        """
        quarter_months = {
            1: (1, 2, 3), 2: (4, 5, 6),
            3: (7, 8, 9), 4: (10, 11, 12),
        }
        allowed_months = quarter_months.get(quarter, tuple(range(1, 13))) if quarter else tuple(range(1, 13))

        schedule: List[TaxLiabilityByPeriod] = []

        for run in self._runs:
            if run.pay_date.year != year or run.pay_date.month not in allowed_months:
                continue

            period = TaxLiabilityByPeriod(
                period_start=run.period_start,
                period_end=run.period_end,
                pay_date=run.pay_date,
            )
            for emp in run.results:
                if emp.status != "CALCULATED":
                    continue
                period.employee_federal_income_tax += emp.federal_income_tax
                period.employee_social_security += emp.social_security_tax
                period.employer_social_security += emp.employer_social_security
                period.employee_medicare += emp.medicare_tax
                period.employer_medicare += emp.employer_medicare

            period.total_941_liability = _round(
                period.employee_federal_income_tax
                + period.employee_social_security + period.employer_social_security
                + period.employee_medicare + period.employer_medicare
                + period.additional_medicare
            )
            schedule.append(period)

        return sorted(schedule, key=lambda p: p.pay_date)

    def liability_schedule_to_csv(self, schedule: List[TaxLiabilityByPeriod]) -> str:
        """Export the liability schedule as CSV."""
        output = io.StringIO()
        fieldnames = [
            "period_start", "period_end", "pay_date",
            "employee_federal_income_tax", "employee_social_security",
            "employer_social_security", "employee_medicare",
            "employer_medicare", "additional_medicare", "total_941_liability",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for p in schedule:
            writer.writerow({
                "period_start": str(p.period_start),
                "period_end": str(p.period_end),
                "pay_date": str(p.pay_date),
                "employee_federal_income_tax": p.employee_federal_income_tax,
                "employee_social_security": p.employee_social_security,
                "employer_social_security": p.employer_social_security,
                "employee_medicare": p.employee_medicare,
                "employer_medicare": p.employer_medicare,
                "additional_medicare": p.additional_medicare,
                "total_941_liability": p.total_941_liability,
            })
        return output.getvalue()
