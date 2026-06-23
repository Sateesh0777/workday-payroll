"""
year_end_reports.py
Year-End Payroll Documents.

Generates W-2 (Wage and Tax Statement) records for each employee and
the W-3 (Transmittal of Wage and Tax Statements) employer summary.
Produces SSA EFW2 electronic file format and human-readable output.
"""

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from src.payroll.payroll_processor import PayrollRunSummary

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


def _round(v: Decimal) -> Decimal:
    from decimal import ROUND_HALF_UP
    return v.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# W-2 Box definitions (2025)
# ---------------------------------------------------------------------------
# Box 1  - Wages, tips, other compensation (federal taxable)
# Box 2  - Federal income tax withheld
# Box 3  - Social security wages
# Box 4  - Social security tax withheld
# Box 5  - Medicare wages and tips
# Box 6  - Medicare tax withheld
# Box 12 - Various codes (401k, etc.)
# Box 16 - State wages
# Box 17 - State income tax


@dataclass
class W2Record:
    """Represents one employee's W-2 for a tax year."""
    tax_year: int

    # Employee info
    worker_id: str
    ssn: str = "***-**-****"     # Masked; real SSN from HR system
    first_name: str = ""
    last_name: str = ""
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""

    # Employer info
    employer_ein: str = ""
    employer_name: str = ""
    employer_address: str = ""
    employer_city_state_zip: str = ""

    # Box values
    box1_wages: Decimal = Decimal("0")           # Federal taxable wages
    box2_federal_tax: Decimal = Decimal("0")     # Federal income tax withheld
    box3_ss_wages: Decimal = Decimal("0")        # Social security wages
    box4_ss_tax: Decimal = Decimal("0")          # Social security tax withheld
    box5_medicare_wages: Decimal = Decimal("0")  # Medicare wages
    box6_medicare_tax: Decimal = Decimal("0")    # Medicare tax withheld
    box12_items: List[Dict] = field(default_factory=list)  # Code + amount
    box13_retirement_plan: bool = False
    box16_state_wages: Decimal = Decimal("0")
    box17_state_tax: Decimal = Decimal("0")
    state_code: str = ""
    state_id_number: str = ""

    def add_box12(self, code: str, amount: Decimal) -> None:
        """Add a Box 12 entry (e.g., D=401k, W=HSA, C=group life imputed)."""
        self.box12_items.append({"code": code, "amount": amount})


@dataclass
class W3Record:
    """W-3 Transmittal — employer-level totals across all W-2s."""
    tax_year: int
    employer_ein: str = ""
    employer_name: str = ""
    employer_address: str = ""
    kind_of_payer: str = "941"   # 941, 943, 944, etc.
    employee_count: int = 0
    box1_wages: Decimal = Decimal("0")
    box2_federal_tax: Decimal = Decimal("0")
    box3_ss_wages: Decimal = Decimal("0")
    box4_ss_tax: Decimal = Decimal("0")
    box5_medicare_wages: Decimal = Decimal("0")
    box6_medicare_tax: Decimal = Decimal("0")
    box16_state_wages: Decimal = Decimal("0")
    box17_state_tax: Decimal = Decimal("0")


# ---------------------------------------------------------------------------
# Year-End Report Generator
# ---------------------------------------------------------------------------

class YearEndReportGenerator:
    """
    Generates W-2 records for all employees and a W-3 transmittal.

    Aggregates payroll run data across an entire tax year to produce
    the correct annual totals for each W-2 box.

    Usage::

        gen = YearEndReportGenerator(
            tax_year=2025,
            employer_ein="12-3456789",
            employer_name="Acme Corp",
        )
        for run in all_2025_runs:
            gen.add_payroll_run(run)

        w2s = gen.generate_w2s()
        w3  = gen.generate_w3(w2s)
        print(gen.w3_to_text(w3))
        csv_data = gen.w2s_to_csv(w2s)
    """

    def __init__(
        self,
        tax_year: int,
        employer_ein: str = "",
        employer_name: str = "",
        employer_address: str = "",
        employer_city_state_zip: str = "",
    ):
        self.tax_year = tax_year
        self.employer_ein = employer_ein
        self.employer_name = employer_name
        self.employer_address = employer_address
        self.employer_city_state_zip = employer_city_state_zip
        self._runs: List[PayrollRunSummary] = []

    def add_payroll_run(self, run: PayrollRunSummary) -> None:
        """Add a completed payroll run to the year-end accumulator."""
        self._runs.append(run)

    def add_payroll_runs(self, runs: List[PayrollRunSummary]) -> None:
        self._runs.extend(runs)

    # ------------------------------------------------------------------
    # W-2 generation
    # ------------------------------------------------------------------

    def generate_w2s(self) -> List[W2Record]:
        """
        Aggregate all payroll runs for the tax year and produce one
        W-2 record per employee.
        """
        # Accumulate per-employee totals
        accum: Dict[str, W2Record] = {}

        for run in self._runs:
            if run.pay_date.year != self.tax_year:
                continue

            for emp in run.results:
                if emp.status != "CALCULATED":
                    continue

                wid = emp.worker_id
                if wid not in accum:
                    # Split full_name into first/last (best-effort)
                    name_parts = emp.full_name.strip().split(" ", 1)
                    first = name_parts[0] if name_parts else ""
                    last = name_parts[1] if len(name_parts) > 1 else ""
                    accum[wid] = W2Record(
                        tax_year=self.tax_year,
                        worker_id=wid,
                        first_name=first,
                        last_name=last,
                        employer_ein=self.employer_ein,
                        employer_name=self.employer_name,
                        employer_address=self.employer_address,
                        employer_city_state_zip=self.employer_city_state_zip,
                    )

                w2 = accum[wid]

                # Box 1: federal taxable wages (gross - pretax deductions)
                box1_add = emp.gross_pay - emp.pretax_deductions - emp.retirement_pretax
                w2.box1_wages += box1_add
                w2.box2_federal_tax += emp.federal_income_tax

                # Box 3/4: SS wages capped at wage base (2025: $176,100)
                w2.box3_ss_wages += emp.gross_pay  # cap applied at W-2 generation
                w2.box4_ss_tax += emp.social_security_tax

                # Box 5/6: Medicare (no wage base cap)
                w2.box5_medicare_wages += emp.gross_pay
                w2.box6_medicare_tax += emp.medicare_tax

                # State wages/tax
                w2.box16_state_wages += emp.gross_pay - emp.pretax_deductions - emp.retirement_pretax
                w2.box17_state_tax += emp.state_income_tax

                # Box 12D: 401(k) pre-tax contributions
                if emp.retirement_pretax > 0:
                    w2.box13_retirement_plan = True

        # Apply SS wage base cap ($176,100 for 2025)
        SS_WAGE_BASE = Decimal("176100")
        w2_list = []
        for w2 in accum.values():
            w2.box1_wages = _round(w2.box1_wages)
            w2.box2_federal_tax = _round(w2.box2_federal_tax)
            w2.box3_ss_wages = _round(min(w2.box3_ss_wages, SS_WAGE_BASE))
            w2.box4_ss_tax = _round(w2.box4_ss_tax)
            w2.box5_medicare_wages = _round(w2.box5_medicare_wages)
            w2.box6_medicare_tax = _round(w2.box6_medicare_tax)
            w2.box16_state_wages = _round(w2.box16_state_wages)
            w2.box17_state_tax = _round(w2.box17_state_tax)
            w2_list.append(w2)

        logger.info("Generated %d W-2 records for tax year %d", len(w2_list), self.tax_year)
        return sorted(w2_list, key=lambda w: w.last_name)

    # ------------------------------------------------------------------
    # W-3 generation
    # ------------------------------------------------------------------

    def generate_w3(self, w2s: List[W2Record]) -> W3Record:
        """Produce the W-3 transmittal from a list of W-2 records."""
        w3 = W3Record(
            tax_year=self.tax_year,
            employer_ein=self.employer_ein,
            employer_name=self.employer_name,
            employer_address=self.employer_address,
            employee_count=len(w2s),
        )
        for w2 in w2s:
            w3.box1_wages += w2.box1_wages
            w3.box2_federal_tax += w2.box2_federal_tax
            w3.box3_ss_wages += w2.box3_ss_wages
            w3.box4_ss_tax += w2.box4_ss_tax
            w3.box5_medicare_wages += w2.box5_medicare_wages
            w3.box6_medicare_tax += w2.box6_medicare_tax
            w3.box16_state_wages += w2.box16_state_wages
            w3.box17_state_tax += w2.box17_state_tax

        w3.box1_wages = _round(w3.box1_wages)
        w3.box2_federal_tax = _round(w3.box2_federal_tax)
        w3.box3_ss_wages = _round(w3.box3_ss_wages)
        w3.box4_ss_tax = _round(w3.box4_ss_tax)
        w3.box5_medicare_wages = _round(w3.box5_medicare_wages)
        w3.box6_medicare_tax = _round(w3.box6_medicare_tax)
        w3.box16_state_wages = _round(w3.box16_state_wages)
        w3.box17_state_tax = _round(w3.box17_state_tax)
        return w3

    # ------------------------------------------------------------------
    # Output formatters
    # ------------------------------------------------------------------

    def w2_to_text(self, w2: W2Record) -> str:
        """Render a single W-2 as formatted text."""
        sep = "=" * 60
        box12_str = ", ".join(
            f"Box12{item['code']}=${item['amount']:,.2f}"
            for item in w2.box12_items
        ) or "None"
        lines = [
            sep,
            f"  W-2 Wage and Tax Statement  ({w2.tax_year})",
            f"  Employee: {w2.last_name}, {w2.first_name}  |  Worker ID: {w2.worker_id}",
            f"  SSN: {w2.ssn}",
            f"  Employer: {w2.employer_name}  EIN: {w2.employer_ein}",
            sep,
            f"  Box 1  - Wages:                    ${w2.box1_wages:>12,.2f}",
            f"  Box 2  - Federal tax withheld:     ${w2.box2_federal_tax:>12,.2f}",
            f"  Box 3  - Social Security wages:    ${w2.box3_ss_wages:>12,.2f}",
            f"  Box 4  - Social Security tax:      ${w2.box4_ss_tax:>12,.2f}",
            f"  Box 5  - Medicare wages:           ${w2.box5_medicare_wages:>12,.2f}",
            f"  Box 6  - Medicare tax withheld:    ${w2.box6_medicare_tax:>12,.2f}",
            f"  Box 12 - Other: {box12_str}",
            f"  Box 13 - Retirement plan: {'Yes' if w2.box13_retirement_plan else 'No'}",
            f"  Box 16 - State wages ({w2.state_code}):      ${w2.box16_state_wages:>12,.2f}",
            f"  Box 17 - State tax withheld:       ${w2.box17_state_tax:>12,.2f}",
            sep,
        ]
        return "\n".join(lines)

    def w3_to_text(self, w3: W3Record) -> str:
        """Render the W-3 transmittal as formatted text."""
        sep = "=" * 60
        lines = [
            sep,
            f"  W-3 Transmittal of Wage and Tax Statements ({w3.tax_year})",
            f"  Employer: {w3.employer_name}  EIN: {w3.employer_ein}",
            f"  Total W-2s: {w3.employee_count}",
            sep,
            f"  Box 1  - Total wages:              ${w3.box1_wages:>12,.2f}",
            f"  Box 2  - Total federal tax:        ${w3.box2_federal_tax:>12,.2f}",
            f"  Box 3  - Total SS wages:           ${w3.box3_ss_wages:>12,.2f}",
            f"  Box 4  - Total SS tax:             ${w3.box4_ss_tax:>12,.2f}",
            f"  Box 5  - Total Medicare wages:     ${w3.box5_medicare_wages:>12,.2f}",
            f"  Box 6  - Total Medicare tax:       ${w3.box6_medicare_tax:>12,.2f}",
            f"  Box 16 - Total state wages:        ${w3.box16_state_wages:>12,.2f}",
            f"  Box 17 - Total state tax:          ${w3.box17_state_tax:>12,.2f}",
            sep,
        ]
        return "\n".join(lines)

    def w2s_to_csv(self, w2s: List[W2Record]) -> str:
        """Export all W-2 records to CSV."""
        output = io.StringIO()
        fieldnames = [
            "tax_year", "worker_id", "ssn", "last_name", "first_name",
            "employer_ein", "employer_name",
            "box1_wages", "box2_federal_tax",
            "box3_ss_wages", "box4_ss_tax",
            "box5_medicare_wages", "box6_medicare_tax",
            "box13_retirement_plan",
            "state_code", "box16_state_wages", "box17_state_tax",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for w2 in w2s:
            writer.writerow({
                "tax_year": w2.tax_year,
                "worker_id": w2.worker_id,
                "ssn": w2.ssn,
                "last_name": w2.last_name,
                "first_name": w2.first_name,
                "employer_ein": w2.employer_ein,
                "employer_name": w2.employer_name,
                "box1_wages": w2.box1_wages,
                "box2_federal_tax": w2.box2_federal_tax,
                "box3_ss_wages": w2.box3_ss_wages,
                "box4_ss_tax": w2.box4_ss_tax,
                "box5_medicare_wages": w2.box5_medicare_wages,
                "box6_medicare_tax": w2.box6_medicare_tax,
                "box13_retirement_plan": w2.box13_retirement_plan,
                "state_code": w2.state_code,
                "box16_state_wages": w2.box16_state_wages,
                "box17_state_tax": w2.box17_state_tax,
            })
        return output.getvalue()

    def w2s_to_json(self, w2s: List[W2Record]) -> str:
        """Export all W-2 records to JSON."""
        records = []
        for w2 in w2s:
            records.append({
                "taxYear": w2.tax_year,
                "workerId": w2.worker_id,
                "ssn": w2.ssn,
                "lastName": w2.last_name,
                "firstName": w2.first_name,
                "employerEIN": w2.employer_ein,
                "employerName": w2.employer_name,
                "box1Wages": str(w2.box1_wages),
                "box2FederalTax": str(w2.box2_federal_tax),
                "box3SsWages": str(w2.box3_ss_wages),
                "box4SsTax": str(w2.box4_ss_tax),
                "box5MedicareWages": str(w2.box5_medicare_wages),
                "box6MedicareTax": str(w2.box6_medicare_tax),
                "box12Items": w2.box12_items,
                "box13RetirementPlan": w2.box13_retirement_plan,
                "stateCode": w2.state_code,
                "box16StateWages": str(w2.box16_state_wages),
                "box17StateTax": str(w2.box17_state_tax),
            })
        return json.dumps({"taxYear": self.tax_year, "w2Records": records}, indent=2)

    def generate_efw2_snippet(self, w2s: List[W2Record], w3: W3Record) -> str:
        """
        Generate a simplified SSA EFW2 electronic filing snippet.
        Each record is fixed-width per SSA Publication 42-007 (RA/RE/RW/RS/RT).
        NOTE: This is a representative subset of fields for illustration.
        A production implementation must include all required fields.
        """
        lines_out = []

        # RA - Submitter record
        lines_out.append(f"RA{w3.employer_ein.replace('-', ''):<9}{w3.employer_name:<57}")

        # RE - Employer record
        lines_out.append(f"RE{w3.tax_year}{w3.employer_ein.replace('-', ''):<9}{w3.employer_name:<57}")

        # RW - Employee wage records
        for w2 in w2s:
            ssn_clean = w2.ssn.replace("-", "").replace("*", "0")
            lines_out.append(
                f"RW{ssn_clean:<9}{w2.last_name:<20}{w2.first_name:<15}"
                f"{int(w2.box1_wages * 100):011d}"
                f"{int(w2.box2_federal_tax * 100):011d}"
                f"{int(w2.box3_ss_wages * 100):011d}"
                f"{int(w2.box4_ss_tax * 100):011d}"
                f"{int(w2.box5_medicare_wages * 100):011d}"
                f"{int(w2.box6_medicare_tax * 100):011d}"
            )

        # RT - Total record
        lines_out.append(
            f"RT{len(w2s):08d}"
            f"{int(w3.box1_wages * 100):015d}"
            f"{int(w3.box2_federal_tax * 100):015d}"
            f"{int(w3.box3_ss_wages * 100):015d}"
            f"{int(w3.box4_ss_tax * 100):015d}"
            f"{int(w3.box5_medicare_wages * 100):015d}"
            f"{int(w3.box6_medicare_tax * 100):015d}"
        )

        return "\n".join(lines_out)
