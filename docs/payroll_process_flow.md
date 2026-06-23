# Payroll Process Flow

This document describes the end-to-end payroll processing workflow,
from schedule generation through payment distribution and year-end reporting.

---

## Overview

```
SCHEDULE         DATA FETCH       CALCULATION      APPROVAL         PAYMENT
   |                 |                |                |                |
Create Run ──► Fetch Workday ──► Gross Pay ──► Approve Run ──► Commit Run
               Workers &         Tax Calc         (HR/Finance)     ACH File
               Time Data         Deductions                        Generation
                                 Net Pay
```

---

## Step 1: Payroll Schedule Setup

**Module**: `src/payroll/payroll_run.py` → `generate_biweekly_schedule()`

At the beginning of each year, generate all 26 payroll run records (for biweekly):

```python
from src.payroll.payroll_run import generate_biweekly_schedule
from datetime import date

runs = generate_biweekly_schedule(
    pay_group="BIWEEKLY-US",
    year=2025,
    first_period_start=date(2025, 1, 1),
    pay_lag_days=3,
)
# Returns 26 PayrollRunRecord objects in SCHEDULED status
```

---

## Step 2: Data Collection

**Modules**: `WorkdayAPIClient`, `TimeTrackingIntegration`

When a pay period ends, the processor fetches:

| Data Type | Source | Module |
|-----------|--------|--------|
| Worker roster | Workday HCM | `workday_api.py` |
| Compensation (salary/hourly) | Workday Compensation | `workday_api.py` |
| Hours worked (regular, OT) | Workday Time Tracking | `time_tracking.py` |
| Benefit elections | Workday Benefits | `workday_api.py` |
| Retirement elections | Workday Retirement | `workday_api.py` |
| Tax withholding elections | Workday Payroll | `workday_api.py` |
| Active garnishments | Workday Payroll | `payroll_processor.py` |

---

## Step 3: Pre-Payroll Validation

**Module**: `PayrollProcessor._fetch_employee_inputs()`

Before calculation, the system validates:
- All workers have pay frequency and compensation set
- Hours worked data is present for hourly employees
- Tax withholding elections exist (defaults to SINGLE/0 if missing)
- Active garnishment orders are current

Workers with missing required data are logged as warnings and skipped.

---

## Step 4: Gross Pay Calculation

**Module**: `CompensationCalculator`

For each employee:

**Salaried employees:**
```
Regular Pay = Annual Salary / Periods Per Year
OT Pay      = (Annual Salary / (Periods * Std Hours)) * (OT Rate - 1) * OT Hours
```

**Hourly employees:**
```
Effective Rate = Hourly Rate + Shift Differential
Regular Pay    = Regular Hours * Effective Rate
OT Pay         = OT Hours * Effective Rate * 1.5
Double Time    = DT Hours * Effective Rate * 2.0
```

**Gross Pay** = Regular + OT + Double Time + Bonus + Commission

---

## Step 5: Pre-Tax Deductions

**Modules**: `RetirementDeductionCalculator`, `BenefitsDeductionCalculator`

Pre-tax deductions reduce taxable wages:

```
Taxable Wages = Gross Pay - 401(k) Pre-Tax - Benefits Pre-Tax
```

Pre-tax items include: 401(k)/403(b), Medical, Dental, Vision, FSA, HSA,
Commuter benefits (transit/parking).

---

## Step 6: Tax Withholding

**Modules**: `FederalTaxCalculator`, `StateTaxCalculator`, `PayrollProcessor`

Applied in order:

| Tax | Rate | Source |
|-----|------|--------|
| Social Security | 6.2% (up to $176,100 wage base) | `tax_tables.py` |
| Medicare | 1.45% (no cap) | `tax_tables.py` |
| Additional Medicare | +0.9% above $200k YTD | `tax_tables.py` |
| Federal Income Tax | IRS Pub 15-T brackets | `federal_tax.py` |
| State Income Tax | State-specific brackets | `state_tax.py` |

Employer matches Social Security and Medicare (6.2% + 1.45% each).

---

## Step 7: Post-Tax Deductions & Garnishments

**Modules**: `BenefitsDeductionCalculator`, `GarnishmentCalculator`

Post-tax deductions:
- Supplemental life insurance
- Critical illness, accident, hospital indemnity
- Roth 401(k) (after-tax)
- Charitable contributions

Garnishments (CCPA Title III priority order):
1. Child support / alimony
2. Federal and state tax levies
3. Student loan garnishments
4. Creditor garnishments

---

## Step 8: Net Pay Calculation

```
Net Pay = Gross Pay
        - Pre-Tax Deductions (benefits + retirement)
        - Federal Income Tax
        - Social Security Tax
        - Medicare Tax
        - State Income Tax
        - Post-Tax Deductions
        - Garnishments
```

---

## Step 9: Approval Workflow

**Module**: `PayrollRunManager.approve()`

The calculated run is presented to HR/Finance for review:
1. Review `PayrollRunSummary` — totals, employee count, error count
2. Resolve any `ERROR` employees manually
3. Approve run: `manager.approve(run_id, approved_by="hr@company.com")`

Approval is blocked if any employee result has `status="ERROR"`.

---

## Step 10: Payment Distribution

**Module**: `DirectDepositManager`

After commit, net pay is distributed per employee bank account elections:
1. Fixed-amount accounts funded first (in priority order)
2. Percentage-based accounts funded next
3. Remainder account receives whatever is left
4. ACH batch generated for bank submission
5. Paper checks issued for employees without direct deposit

---

## Step 11: Payroll Reporting

**Modules**: `PayrollSummaryReport`, `TaxReportGenerator`

After each payroll run:
- **Pay stubs**: Line items from `EmployeePayrollResult.line_items`
- **Payroll register**: CSV/JSON via `PayrollSummaryReport`
- **Tax deposit schedule**: Via `TaxReportGenerator.generate_liability_schedule()`

---

## Step 12: Quarterly Tax Filing (Form 941)

At the end of each quarter:

```python
generator = TaxReportGenerator(employer_ein="12-3456789", employer_name="Acme")
for run in q1_runs:
    generator.add_payroll_run(run)
form_941 = generator.generate_form_941(quarter=1, year=2025)
print(generator.form_941_to_text(form_941))
```

**Due dates**: April 30 (Q1), July 31 (Q2), October 31 (Q3), January 31 (Q4)

---

## Step 13: Annual Tax Filing

At year-end:

**Form 940 (FUTA)**:
```python
form_940 = generator.generate_form_940(year=2025)
```
Due: January 31 of following year.

**W-2 / W-3**:
```python
gen = YearEndReportGenerator(tax_year=2025, employer_ein="12-3456789", ...)
for run in all_2025_runs:
    gen.add_payroll_run(run)
w2s = gen.generate_w2s()
w3  = gen.generate_w3(w2s)
efw2 = gen.generate_efw2_snippet(w2s, w3)  # SSA electronic filing
```
**Due**: W-2 to employees and SSA by January 31.

---

## Error Handling

| Error Type | Handling |
|-----------|----------|
| Workday API timeout | Retry up to `max_retries` times with backoff |
| Missing worker data | Log warning, skip worker, add to `run.errors` |
| Calculation error | Employee marked `status=ERROR`, included in summary |
| Approval blocked | Run stays `CALCULATED` until errors resolved |
| CCPA garnishment cap | Warning in `GarnishmentResult.warnings` |
| IRS limit exceeded | Premium capped, warning added to deduction result |
