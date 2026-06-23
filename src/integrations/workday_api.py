"""
workday_api.py
Workday HCM REST API Client with OAuth2 authentication.
Handles authentication, token refresh, and all Workday API interactions
for the Payroll module.
"""

import logging
import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class WorkdayConfig:
    """Configuration for Workday API connection."""
    tenant: str
    base_url: str
    client_id: str
    client_secret: str
    token_url: str = ""
    api_version: str = "v1"
    timeout: int = 30

    def __post_init__(self):
        if not self.token_url:
            self.token_url = (
                f"https://{self.tenant}.workday.com/ccx/oauth2/{self.tenant}/token"
            )


@dataclass
class OAuthToken:
    """Represents a Workday OAuth2 access token."""
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    issued_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_expired(self) -> bool:
        expiry = self.issued_at + timedelta(seconds=self.expires_in - 60)
        return datetime.utcnow() >= expiry

    @property
    def authorization_header(self) -> str:
        return f"{self.token_type} {self.access_token}"


class WorkdayAPIError(Exception):
    """Custom exception for Workday API errors."""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response or {}


class WorkdayAPIClient:
    """
    Workday HCM REST API Client.

    Handles OAuth2 client credentials flow, automatic token refresh,
    and provides methods for all Payroll-related API endpoints.

    Usage:
        config = WorkdayConfig(
            tenant="mycompany",
            base_url="https://wd2-impl-services1.workday.com",
            client_id="your-client-id",
            client_secret="your-client-secret"
        )
        client = WorkdayAPIClient(config)
        employees = client.get_all_workers()
    """

    def __init__(self, config: WorkdayConfig):
        self.config = config
        self._token: Optional[OAuthToken] = None
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def authenticate(self) -> OAuthToken:
        """Obtain OAuth2 access token using client credentials grant."""
        logger.info("Authenticating with Workday API...")
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
        }
        try:
            response = requests.post(
                self.config.token_url,
                data=payload,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            data = response.json()
            self._token = OAuthToken(
                access_token=data["access_token"],
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in", 3600),
                refresh_token=data.get("refresh_token"),
            )
            logger.info("Authentication successful. Token expires in %ds", self._token.expires_in)
            return self._token
        except requests.HTTPError as e:
            raise WorkdayAPIError(
                f"Authentication failed: {e}",
                status_code=e.response.status_code if e.response else None
            )

    def _ensure_authenticated(self):
        """Ensure a valid token is available, refreshing if necessary."""
        if self._token is None or self._token.is_expired:
            self.authenticate()
        self._session.headers["Authorization"] = self._token.authorization_header

    # -------------------------------------------------------------------------
    # Core HTTP methods
    # -------------------------------------------------------------------------

    def _build_url(self, endpoint: str) -> str:
        return (
            f"{self.config.base_url}/ccx/api/payroll/{self.config.api_version}"
            f"/{self.config.tenant}/{endpoint}"
        )

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        self._ensure_authenticated()
        url = self._build_url(endpoint)
        try:
            resp = self._session.get(url, params=params, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            raise WorkdayAPIError(
                f"GET {url} failed: {e}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else {}
            )

    def _post(self, endpoint: str, payload: Dict) -> Dict:
        self._ensure_authenticated()
        url = self._build_url(endpoint)
        try:
            resp = self._session.post(url, json=payload, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            raise WorkdayAPIError(
                f"POST {url} failed: {e}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else {}
            )

    def _put(self, endpoint: str, payload: Dict) -> Dict:
        self._ensure_authenticated()
        url = self._build_url(endpoint)
        try:
            resp = self._session.put(url, json=payload, timeout=self.config.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            raise WorkdayAPIError(
                f"PUT {url} failed: {e}",
                status_code=e.response.status_code,
                response=e.response.json() if e.response else {}
            )

    def _paginate(self, endpoint: str, params: Dict = None) -> List[Dict]:
        """Handle Workday API pagination, returning all records."""
        params = params or {}
        params["limit"] = params.get("limit", 100)
        params["offset"] = 0
        results = []
        while True:
            data = self._get(endpoint, params)
            records = data.get("data", [])
            results.extend(records)
            total = data.get("total", len(records))
            params["offset"] += len(records)
            if params["offset"] >= total or not records:
                break
        return results

    # -------------------------------------------------------------------------
    # Worker / Employee Endpoints
    # -------------------------------------------------------------------------

    def get_all_workers(self, as_of_date: str = None) -> List[Dict]:
        """Retrieve all active workers from Workday."""
        params = {}
        if as_of_date:
            params["asOfDate"] = as_of_date
        return self._paginate("workers", params)

    def get_worker(self, worker_id: str) -> Dict:
        """Get a single worker by Workday Worker ID."""
        return self._get(f"workers/{worker_id}")

    def get_worker_compensation(self, worker_id: str) -> Dict:
        """Get compensation details for a worker."""
        return self._get(f"workers/{worker_id}/compensation")

    def get_worker_deductions(self, worker_id: str) -> List[Dict]:
        """Get all active deductions for a worker."""
        return self._paginate(f"workers/{worker_id}/payrollDeductions")

    def get_worker_tax_elections(self, worker_id: str) -> Dict:
        """Get federal and state tax withholding elections for a worker."""
        return self._get(f"workers/{worker_id}/taxElections")

    def get_worker_time_off_balances(self, worker_id: str) -> List[Dict]:
        """Get time off / absence balances for a worker."""
        return self._paginate(f"workers/{worker_id}/timeOffBalances")

    # -------------------------------------------------------------------------
    # Payroll Run Endpoints
    # -------------------------------------------------------------------------

    def get_payroll_runs(self, period_start: str = None, period_end: str = None) -> List[Dict]:
        """Retrieve payroll runs, optionally filtered by pay period."""
        params = {}
        if period_start:
            params["periodStartDate"] = period_start
        if period_end:
            params["periodEndDate"] = period_end
        return self._paginate("payrollRuns", params)

    def get_payroll_run(self, run_id: str) -> Dict:
        """Get details of a specific payroll run."""
        return self._get(f"payrollRuns/{run_id}")

    def create_payroll_run(self, payload: Dict) -> Dict:
        """
        Initiate a new payroll run.
        Payload keys: payGroup, periodStartDate, periodEndDate, payDate, runType
        """
        logger.info("Creating payroll run for period %s - %s",
                    payload.get("periodStartDate"), payload.get("periodEndDate"))
        return self._post("payrollRuns", payload)

    def submit_payroll_run(self, run_id: str) -> Dict:
        """Submit a payroll run for processing."""
        return self._put(f"payrollRuns/{run_id}/submit", {})

    def get_payroll_run_results(self, run_id: str) -> List[Dict]:
        """Get individual payroll calculation results for a run."""
        return self._paginate(f"payrollRuns/{run_id}/results")

    # -------------------------------------------------------------------------
    # Pay Slips
    # -------------------------------------------------------------------------

    def get_pay_slips(self, worker_id: str, from_date: str = None, to_date: str = None) -> List[Dict]:
        """Get pay slips for a worker, optionally filtered by date range."""
        params = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        return self._paginate(f"workers/{worker_id}/paySlips", params)

    def get_pay_slip(self, worker_id: str, pay_slip_id: str) -> Dict:
        """Get a specific pay slip by ID."""
        return self._get(f"workers/{worker_id}/paySlips/{pay_slip_id}")

    # -------------------------------------------------------------------------
    # Pay Groups
    # -------------------------------------------------------------------------

    def get_pay_groups(self) -> List[Dict]:
        """Get all pay groups defined in Workday."""
        return self._paginate("payGroups")

    def get_pay_group(self, pay_group_id: str) -> Dict:
        """Get details of a specific pay group."""
        return self._get(f"payGroups/{pay_group_id}")

    # -------------------------------------------------------------------------
    # Earnings & Deduction Codes
    # -------------------------------------------------------------------------

    def get_earning_codes(self) -> List[Dict]:
        """Get all earning codes (salary, overtime, bonus, etc.)."""
        return self._paginate("earningCodes")

    def get_deduction_codes(self) -> List[Dict]:
        """Get all deduction codes (benefits, retirement, garnishments)."""
        return self._paginate("deductionCodes")

    # -------------------------------------------------------------------------
    # Tax Filing
    # -------------------------------------------------------------------------

    def get_tax_documents(self, tax_year: int, document_type: str = "W2") -> List[Dict]:
        """Retrieve year-end tax documents (W-2, 1099, etc.)."""
        params = {"taxYear": tax_year, "documentType": document_type}
        return self._paginate("taxDocuments", params)

    def get_payroll_tax_summary(self, period_start: str, period_end: str) -> Dict:
        """Get aggregate payroll tax summary for a date range."""
        params = {"periodStartDate": period_start, "periodEndDate": period_end}
        return self._get("taxSummary", params)

    # -------------------------------------------------------------------------
    # Direct Deposit
    # -------------------------------------------------------------------------

    def get_direct_deposit_accounts(self, worker_id: str) -> List[Dict]:
        """Get direct deposit bank accounts for a worker."""
        return self._paginate(f"workers/{worker_id}/directDepositAccounts")

    def update_direct_deposit(self, worker_id: str, account_id: str, payload: Dict) -> Dict:
        """Update a direct deposit account for a worker."""
        return self._put(
            f"workers/{worker_id}/directDepositAccounts/{account_id}", payload
        )

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    def health_check(self) -> bool:
        """Verify connectivity to Workday API."""
        try:
            self.authenticate()
            return True
        except WorkdayAPIError:
            return False

    def __repr__(self) -> str:
        return f"WorkdayAPIClient(tenant={self.config.tenant!r}, version={self.config.api_version!r})"
