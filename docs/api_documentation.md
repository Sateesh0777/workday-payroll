# API Documentation

This document describes the public API of each module in the workday-payroll project.

---

## PayrollRunManager (`src/payroll/payroll_run.py`)

Manages the lifecycle of a payroll run from creation to commitment.

### `create_run(pay_group, period_start, period_end, pay_date, run_type, pay_frequency, worker_ids) -> PayrollRunRecord`
Creates a new run in `DRAFT` status.

### `calculate(run_id) -> PayrollRunRecord`
Executes gross-to-net calculations. Transitions to `CALCULATED`.

### `approve(run_id, approved_by) -> PayrollRunRecord`
Marks run as `APPROVED`. Raises `ValueError` if unresolved errors exist.

### `commit(run_id) -> PayrollRunRecord`
Finalizes run (`COMMITTED`) and triggers payment distribution.

### `void_run(run_id, reason) -> PayrollRunRecord`
Voids any non-committed run.

### `list_runs(pay_group, status) -> List[PayrollRunRecord]`
Returns runs filtered by pay group or status, newest first.

---

## PayrollProcessor (`src/payroll/payroll_processor.py`)

Core gross-to-net engine.

### `process_payroll_run(run_id, pay_group, period_start, period_end, pay_date, worker_ids) -> PayrollRunSummary`
Fetches all employee data, calculates payroll, returns aggregate summary.

### `_calculate_employee_payroll(emp, period_start, period_end, pay_date) -> EmployeePayrollResult`
Full calculation pipeline for one employee:
1. Gross pay (regular + OT + bonus + commission)
2. Pre-tax deductions (retirement + benefits)
3. FICA taxes (SS + Medicare)
4. Federal income tax
5. State income tax
6. Post-tax deductions + garnishments
7. Net pay
8. Line items for pay slip

---

## CompensationCalculator (`src/payroll/compensation_calculator.py`)

### `calculate_gross_pay(annual_salary, hourly_rate, hours_worked, overtime_hours, pay_period, double_time_hours, shift_differential) -> Tuple[Decimal, Decimal]`
Returns `(regular_pay, overtime_pay)`. Routes to salaried or hourly logic.

### `calculate_california_overtime(hourly_rate, daily_hours, shift_differential) -> GrossPayResult`
California daily overtime rules: >8h/day = 1.5x, >12h/day = 2x, 7th day = 1.5x/2x.

### `prorate_salary(annual_salary, pay_frequency, days_in_period, working_days_in_period) -> Decimal`
Prorates salary for mid-period hires/terminations.

---

## FederalTaxCalculator (`src/tax/federal_tax.py`)

### `calculate(taxable_wages, pay_frequency, filing_status, allowances, additional_withholding) -> Decimal`
IRS Pub 15-T percentage method withholding.
- Supports: `SINGLE`, `MARRIED`, `HEAD_OF_HOUSEHOLD`
- Handles pre-2020 and 2020+ W-4 forms
- Returns period tax amount (Decimal)

---

## StateTaxCalculator (`src/tax/state_tax.py`)

### `calculate(taxable_wages, state_code, pay_frequency, filing_status, allowances, additional_withholding) -> Decimal`
State income tax withholding. Returns `Decimal("0")` for no-income-tax states.
Raises `NotImplementedError` for states not yet implemented.

---

## BenefitsDeductionCalculator (`src/deductions/benefits_deduction.py`)

### `calculate(elections: List[Dict]) -> BenefitsDeductionResult`
Processes Workday benefit election dicts. Returns:
- `pretax_total` — Section 125 / HSA / FSA deductions
- `posttax_total` — Supplemental life, critical illness, etc.
- `employer_contribution` — Employer-paid premiums
- `warnings` — IRS limit violations or cap events

### `imputed_income(employer_life_face_value, employee_age, periods_per_year) -> Decimal`
IRS Table I imputed income for employer-paid life insurance over $50,000.

---

## RetirementDeductionCalculator (`src/deductions/retirement_deduction.py`)

### `calculate(elections: List[Dict], gross_pay: Decimal) -> RetirementDeductionResult`
Processes 401(k), 403(b), Roth 401(k) elections. Enforces 2025 IRS limits.
Returns:
- `pretax_401k` — Traditional pre-tax contributions
- `roth_401k` — Roth after-tax contributions
- `employer_match` — Employer matching contribution

---

## GarnishmentCalculator (`src/deductions/garnishment.py`)

### `calculate(orders, gross_pay, pretax_deductions, federal_tax, state_tax, fica, pay_frequency) -> GarnishmentResult`
CCPA Title III compliant garnishment processing.
- Priority order: child support > alimony > tax levy > student loan > creditor
- Enforces 30x minimum wage protection
- Caps per CCPA percentage limits by garnishment type

---

## TimeTrackingIntegration (`src/integrations/time_tracking.py`)

### `get_period_summaries(pay_group, period_start, period_end, worker_ids, require_approved) -> List[WorkerTimeSummary]`
Fetches and aggregates approved time entries from Workday for all workers.

### `auto_detect_overtime(summary) -> WorkerTimeSummary`
Reclassifies hours beyond 40/week from regular to overtime if not already classified.

---

## DirectDepositManager (`src/integrations/direct_deposit.py`)

### `distribute(worker_id, full_name, net_pay, accounts, payment_date, payroll_run_id) -> DirectDepositResult`
Distributes net pay across bank accounts in priority order: fixed → percentage → remainder.

### `generate_ach_batch(results, company_name, company_id, effective_date) -> List[Dict]`
Produces NACHA-compatible ACH entry detail records.

---

## TaxReportGenerator (`src/reports/tax_reports.py`)

### `generate_form_941(quarter, year) -> Form941LineItems`
Aggregates payroll run data into IRS Form 941 line items for a calendar quarter.

### `generate_form_940(year) -> Form940Summary`
Annual FUTA tax return (Form 940) with SUTA credit applied.

### `generate_liability_schedule(year, quarter) -> List[TaxLiabilityByPeriod]`
Period-by-period 941 deposit liability schedule for semi-weekly/monthly depositors.

---

## YearEndReportGenerator (`src/reports/year_end_reports.py`)

### `generate_w2s() -> List[W2Record]`
Produces one W-2 record per employee from all registered payroll runs in the tax year.

### `generate_w3(w2s) -> W3Record`
W-3 transmittal: employer totals across all W-2s.

### `w2s_to_csv(w2s) -> str`
### `w2s_to_json(w2s) -> str`
### `generate_efw2_snippet(w2s, w3) -> str`
SSA EFW2 electronic filing format (representative subset of fields).

---

## PayrollSummaryReport (`src/reports/payroll_summary.py`)

### `to_text() -> str` — Human-readable pay run summary
### `to_csv() -> str` — Per-employee CSV for spreadsheet import
### `to_json(indent) -> str` — JSON for system integrations
