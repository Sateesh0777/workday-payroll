# Setup Guide

## Prerequisites

- Python 3.9 or higher
- A Workday HCM tenant with Payroll module access
- Workday API credentials (OAuth2 Client ID and Client Secret)
- Git

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Sateesh0777/workday-payroll.git
cd workday-payroll
```

### 2. Create a Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate       # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

For development (includes linting and testing tools):

```bash
pip install -e ".[dev]"
```

### 4. Configure Workday Credentials

Copy the configuration template and fill in your details:

```bash
cp config/workday_config.yaml config/workday_config.local.yaml
```

Edit `config/workday_config.local.yaml` with your Workday tenant information.

> **Security**: Never commit real credentials. Use environment variables instead:

```bash
export WORKDAY_CLIENT_ID="your-client-id"
export WORKDAY_CLIENT_SECRET="your-client-secret"
```

### 5. Configure Tax Settings

Review `config/tax_config.yaml` and update if needed for your state or custom
tax treatment. The defaults are set to 2025 IRS values.

### 6. Run Tests

```bash
pytest tests/ -v
```

With coverage:

```bash
pytest tests/ --cov=src --cov-report=html
open htmlcov/index.html
```

## Workday API Setup

### Create an API Client in Workday

1. Log into Workday as a System Administrator
2. Navigate to **System > OAuth 2.0 Clients**
3. Click **Create API Client**
4. Set:
   - **Name**: Payroll Integration
   - **Client Grant Type**: Client Credentials
   - **Scope**: Payroll, HCM (Worker Data), Benefits
5. Copy the **Client ID** and **Client Secret**
6. Set the token URL to: `https://<tenant>.workday.com/ccx/oauth2/<tenant>/token`

### Required Workday Permissions

The integration user needs the following Workday security groups:

| Domain | Permission |
|--------|-----------|
| Worker Data | Get |
| Payroll Processing | Get, Put |
| Compensation | Get |
| Benefits | Get |
| Time Tracking | Get |

## Project Structure

```
workday-payroll/
├── src/
│   ├── payroll/          # Core payroll engine
│   ├── tax/              # Tax calculators and tables
│   ├── deductions/       # Benefits, retirement, garnishments
│   ├── integrations/     # Workday API, time tracking, direct deposit
│   └── reports/          # Payroll summaries, tax reports, W-2/W-3
├── tests/                # Unit tests (pytest)
├── config/               # YAML configuration templates
├── docs/                 # Documentation
├── requirements.txt      # Python dependencies
└── pyproject.toml        # Package metadata
```

## Running Your First Payroll

```python
from datetime import date
from src.integrations.workday_api import WorkdayAPIClient, WorkdayConfig
from src.payroll.payroll_run import PayrollRunManager

# 1. Connect to Workday
config = WorkdayConfig(
    tenant="your-tenant",
    base_url="https://wd2-impl-services1.workday.com",
    client_id="your-client-id",
    client_secret="your-client-secret",
)
client = WorkdayAPIClient(config)

# 2. Create a payroll run
manager = PayrollRunManager(client)
run = manager.create_run(
    pay_group="BIWEEKLY-US",
    period_start=date(2025, 1, 1),
    period_end=date(2025, 1, 14),
    pay_date=date(2025, 1, 17),
)

# 3. Calculate, approve, commit
run = manager.calculate(run.run_id)
run = manager.approve(run.run_id, approved_by="hr@company.com")
run = manager.commit(run.run_id)

print(f"Payroll complete: {run.summary.employee_count} employees, net={run.summary.total_net}")
```

## Troubleshooting

**Authentication errors**: Verify your `client_id` and `client_secret` are correct
and the OAuth2 client is active in Workday.

**Worker data not fetching**: Ensure the integration user has the correct security
group memberships in Workday.

**Tax calculation differences**: Check `config/tax_config.yaml` for the correct
tax year and verify allowance/deduction elections in Workday.

**Import errors**: Make sure you installed the package with `pip install -e .`
so that `src.*` imports resolve correctly.
