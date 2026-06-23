"""
payroll_summary.py
Payroll Summary Report Generator.

Produces structured payroll summary reports for a pay run, including
per-employee pay details and tax liability summaries for audit purposes.
"""

import csv
import io
import json
import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List

from src.payroll.payroll_processor import EmployeePayrollResult, PayrollRunSummary

logger = logging.getLogger(__name__)


class PayrollSummaryReport:
    """
    Generates formatted payroll summary reports from a PayrollRunSummary.

    Supports output as plain text, CSV, and JSON.

    Usage:
        report = PayrollSummaryReport(summary)
        print(report.to_text())
        csv_content = report.to_csv()
    """

    def __init__(self, summary: PayrollRunSummary):
        self.summary = summary

    def to_text(self) -> str:
        """Generate a human-readable text summary."""
        s = self.summary
        sep = "=" * 70
        dash = "-" * 70
        lines = [
            sep,
            f"  PAYROLL RUN SUMMARY  |  Run: {s.run_id}",
            sep,
            f"  Pay Group:      {s.pay_group}",
            f"  Period:         {s.period_start} to {s.period_end}",
            f"  Pay Date:       {s.pay_date}",
            f"  Employees:      {s.employee_count}",
            dash,
            f"  Total Gross Pay:          ${s.total_gross:>14,.2f}",
            f"  Total Taxes:              ${s.total_taxes:>14,.2f}",
            f"  Total Net Pay:            ${s.total_net:>14,.2f}",
            dash,
            f"  Employer SS Contribution: ${s.total_employer_ss:>14,.2f}",
            f"  Employer Medicare:        ${s.total_employer_medicare:>14,.2f}",
            f"  Employer Benefits:        ${s.total_employer_benefits:>14,.2f}",
            sep,
        ]
        if s.errors:
            lines.append(f"  ERRORS ({len(s.errors)}):")
            for err in s.errors:
                lines.append(f"    * {err}")
            lines.append(sep)
        lines.append("")
        lines.append("EMPLOYEE DETAIL:")
        header = f"  {'NAME':<30} {'GROSS':>10} {'TAXES':>10} {'NET':>10} {'STATUS'}"
        lines.append(header)
        lines.append("  " + "-" * 70)
        for r in s.results:
            lines.append(
                f"  {r.full_name:<30} "
                f"${r.gross_pay:>9,.2f} "
                f"${r.total_taxes:>9,.2f} "
                f"${r.net_pay:>9,.2f} "
                f"{r.status}"
            )
        lines.append("")
        return "\n".join(lines)

    def to_csv(self) -> str:
        """Generate CSV output suitable for spreadsheet import."""
        output = io.StringIO()
        fieldnames = [
            "run_id", "worker_id", "full_name", "period_start", "period_end", "pay_date",
            "regular_pay", "overtime_pay", "bonus_pay", "commission_pay", "gross_pay",
            "federal_income_tax", "social_security_tax", "medicare_tax", "state_income_tax",
            "total_taxes", "pretax_deductions", "posttax_deductions",
            "retirement_pretax", "retirement_roth", "garnishments", "total_deductions",
            "net_pay", "employer_social_security", "employer_medicare",
            "employer_benefits_contribution", "status", "error_message",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for r in self.summary.results:
            writer.writerow({
                "run_id": self.summary.run_id,
                "worker_id": r.worker_id,
                "full_name": r.full_name,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "pay_date": str(r.pay_date),
                "regular_pay": r.regular_pay,
                "overtime_pay": r.overtime_pay,
                "bonus_pay": r.bonus_pay,
                "commission_pay": r.commission_pay,
                "gross_pay": r.gross_pay,
                "federal_income_tax": r.federal_income_tax,
                "social_security_tax": r.social_security_tax,
                "medicare_tax": r.medicare_tax,
                "state_income_tax": r.state_income_tax,
                "total_taxes": r.total_taxes,
                "pretax_deductions": r.pretax_deductions,
                "posttax_deductions": r.posttax_deductions,
                "retirement_pretax": r.retirement_pretax,
                "retirement_roth": r.retirement_roth,
                "garnishments": r.garnishments,
                "total_deductions": r.total_deductions,
                "net_pay": r.net_pay,
                "employer_social_security": r.employer_social_security,
                "employer_medicare": r.employer_medicare,
                "employer_benefits_contribution": r.employer_benefits_contribution,
                "status": r.status,
                "error_message": r.error_message,
            })
        return output.getvalue()

    def to_json(self, indent: int = 2) -> str:
        """Generate JSON output for system integrations."""
        s = self.summary
        data = {
            "runId": s.run_id,
            "payGroup": s.pay_group,
            "periodStart": str(s.period_start),
            "periodEnd": str(s.period_end),
            "payDate": str(s.pay_date),
            "employeeCount": s.employee_count,
            "totals": {
                "grossPay": str(s.total_gross),
                "taxes": str(s.total_taxes),
                "deductions": str(s.total_deductions),
                "netPay": str(s.total_net),
                "employerSocialSecurity": str(s.total_employer_ss),
                "employerMedicare": str(s.total_employer_medicare),
                "employerBenefits": str(s.total_employer_benefits),
            },
            "errors": s.errors,
            "employees": [
                {
                    "workerId": r.worker_id,
                    "fullName": r.full_name,
                    "grossPay": str(r.gross_pay),
                    "totalTaxes": str(r.total_taxes),
                    "totalDeductions": str(r.total_deductions),
                    "netPay": str(r.net_pay),
                    "federalTax": str(r.federal_income_tax),
                    "stateTax": str(r.state_income_tax),
                    "socialSecurity": str(r.social_security_tax),
                    "medicare": str(r.medicare_tax),
                    "retirementPretax": str(r.retirement_pretax),
                    "retirementRoth": str(r.retirement_roth),
                    "status": r.status,
                }
                for r in s.results
            ],
        }
        return json.dumps(data, indent=indent)

    def by_pay_group(self) -> Dict[str, Dict]:
        """Return aggregate totals grouped by pay group."""
        return {
            self.summary.pay_group: {
                "employee_count": self.summary.employee_count,
                "gross_pay": self.summary.total_gross,
                "total_taxes": self.summary.total_taxes,
                "total_deductions": self.summary.total_deductions,
                "net_pay": self.summary.total_net,
            }
        }
