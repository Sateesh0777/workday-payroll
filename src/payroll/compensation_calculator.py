"""
compensation_calculator.py
Employee Gross Pay Calculator.

Handles regular pay, overtime, shift differentials, and bonus calculations
for both hourly and salaried employees across different pay frequencies.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Tuple

TWO_PLACES = Decimal("0.01")


def _round(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


# Periods per year for each pay frequency
PERIODS_PER_YEAR = {
    "WEEKLY": 52,
    "BIWEEKLY": 26,
    "SEMIMONTHLY": 24,
    "MONTHLY": 12,
}

# Standard working hours per period
STANDARD_HOURS_PER_PERIOD = {
    "WEEKLY": Decimal("40"),
    "BIWEEKLY": Decimal("80"),
    "SEMIMONTHLY": Decimal("86.67"),
    "MONTHLY": Decimal("173.33"),
}

# Overtime multipliers
OVERTIME_MULTIPLIER = Decimal("1.5")      # Standard OT (time-and-a-half)
DOUBLE_TIME_MULTIPLIER = Decimal("2.0")    # Double time (some states/industries)


@dataclass
class PayPeriod:
    """Represents a single pay period."""
    frequency: str
    start_date: date
    end_date: date

    @property
    def periods_per_year(self) -> int:
        return PERIODS_PER_YEAR.get(self.frequency.upper(), 26)

    @property
    def standard_hours(self) -> Decimal:
        return STANDARD_HOURS_PER_PERIOD.get(self.frequency.upper(), Decimal("80"))


@dataclass
class GrossPayResult:
    """Breakdown of gross pay components."""
    regular_pay: Decimal
    overtime_pay: Decimal
    double_time_pay: Decimal
    total_gross: Decimal
    effective_hourly_rate: Decimal


class CompensationCalculator:
    """
    Calculates employee gross pay for a pay period.

    Supports:
    - Salaried employees (annual salary divided by pay periods)
    - Hourly employees (rate x hours + overtime premium)
    - Shift differentials
    - Multiple overtime rules (standard, California daily OT)
    """

    def calculate_gross_pay(
        self,
        annual_salary: Decimal,
        hourly_rate: Decimal,
        hours_worked: Decimal,
        overtime_hours: Decimal,
        pay_period: PayPeriod,
        double_time_hours: Decimal = Decimal("0"),
        shift_differential: Decimal = Decimal("0"),
    ) -> Tuple[Decimal, Decimal]:
        """
        Calculate regular pay and overtime pay for the period.

        Returns:
            (regular_pay, overtime_pay) as a tuple of Decimals.
        """
        if annual_salary and annual_salary > 0:
            return self._salaried_pay(
                annual_salary, overtime_hours, double_time_hours, pay_period
            )
        else:
            return self._hourly_pay(
                hourly_rate, hours_worked, overtime_hours, double_time_hours,
                shift_differential
            )

    def _salaried_pay(
        self,
        annual_salary: Decimal,
        overtime_hours: Decimal,
        double_time_hours: Decimal,
        pay_period: PayPeriod,
    ) -> Tuple[Decimal, Decimal]:
        """Compute salaried employee pay."""
        periods = Decimal(str(pay_period.periods_per_year))
        regular_pay = _round(annual_salary / periods)

        overtime_pay = Decimal("0")
        if overtime_hours and overtime_hours > 0:
            # Hourly equivalent rate for OT calculation
            equivalent_hourly = _round(annual_salary / (periods * pay_period.standard_hours))
            ot_premium = _round(equivalent_hourly * (OVERTIME_MULTIPLIER - 1))
            overtime_pay += _round(overtime_hours * ot_premium)
        if double_time_hours and double_time_hours > 0:
            equivalent_hourly = _round(annual_salary / (periods * pay_period.standard_hours))
            dt_premium = _round(equivalent_hourly * (DOUBLE_TIME_MULTIPLIER - 1))
            overtime_pay += _round(double_time_hours * dt_premium)

        return regular_pay, overtime_pay

    def _hourly_pay(
        self,
        hourly_rate: Decimal,
        hours_worked: Decimal,
        overtime_hours: Decimal,
        double_time_hours: Decimal,
        shift_differential: Decimal,
    ) -> Tuple[Decimal, Decimal]:
        """Compute hourly employee pay."""
        effective_rate = hourly_rate + shift_differential
        regular_hours = max(Decimal("0"), hours_worked - overtime_hours - double_time_hours)
        regular_pay = _round(regular_hours * effective_rate)

        overtime_pay = Decimal("0")
        if overtime_hours > 0:
            ot_rate = _round(effective_rate * OVERTIME_MULTIPLIER)
            overtime_pay += _round(overtime_hours * ot_rate)
        if double_time_hours > 0:
            dt_rate = _round(effective_rate * DOUBLE_TIME_MULTIPLIER)
            overtime_pay += _round(double_time_hours * dt_rate)

        return regular_pay, overtime_pay

    def calculate_annualized_salary(
        self, hourly_rate: Decimal, pay_frequency: str = "BIWEEKLY"
    ) -> Decimal:
        """Annualize an hourly rate."""
        periods = Decimal(str(PERIODS_PER_YEAR.get(pay_frequency.upper(), 26)))
        standard_hours = STANDARD_HOURS_PER_PERIOD.get(pay_frequency.upper(), Decimal("80"))
        return _round(hourly_rate * standard_hours * periods)

    def calculate_hourly_equivalent(
        self, annual_salary: Decimal, pay_frequency: str = "BIWEEKLY"
    ) -> Decimal:
        """Convert annual salary to hourly equivalent rate."""
        periods = Decimal(str(PERIODS_PER_YEAR.get(pay_frequency.upper(), 26)))
        standard_hours = STANDARD_HOURS_PER_PERIOD.get(pay_frequency.upper(), Decimal("80"))
        return _round(annual_salary / (periods * standard_hours))

    def calculate_california_overtime(
        self,
        hourly_rate: Decimal,
        daily_hours: list,           # List of hours per day for the week
        shift_differential: Decimal = Decimal("0"),
    ) -> GrossPayResult:
        """
        California overtime rules:
        - Over 8 hours/day = 1.5x
        - Over 12 hours/day = 2.0x
        - 7th consecutive day first 8 hours = 1.5x
        - 7th consecutive day over 8 hours = 2.0x
        - Over 40 hours/week = 1.5x (whichever gives more pay)
        """
        effective_rate = hourly_rate + shift_differential
        regular_pay = Decimal("0")
        ot_pay = Decimal("0")
        dt_pay = Decimal("0")

        for day_idx, hours in enumerate(daily_hours[:7]):
            hours = Decimal(str(hours))
            is_seventh_day = day_idx == 6

            if is_seventh_day:
                eighth_hour = min(hours, Decimal("8"))
                over_eight = max(Decimal("0"), hours - Decimal("8"))
                ot_pay += _round(eighth_hour * effective_rate * OVERTIME_MULTIPLIER)
                dt_pay += _round(over_eight * effective_rate * DOUBLE_TIME_MULTIPLIER)
            else:
                first_eight = min(hours, Decimal("8"))
                nine_to_twelve = max(Decimal("0"), min(hours, Decimal("12")) - Decimal("8"))
                over_twelve = max(Decimal("0"), hours - Decimal("12"))
                regular_pay += _round(first_eight * effective_rate)
                ot_pay += _round(nine_to_twelve * effective_rate * OVERTIME_MULTIPLIER)
                dt_pay += _round(over_twelve * effective_rate * DOUBLE_TIME_MULTIPLIER)

        total_gross = _round(regular_pay + ot_pay + dt_pay)
        return GrossPayResult(
            regular_pay=regular_pay,
            overtime_pay=ot_pay,
            double_time_pay=dt_pay,
            total_gross=total_gross,
            effective_hourly_rate=effective_rate,
        )

    def prorate_salary(
        self,
        annual_salary: Decimal,
        pay_frequency: str,
        days_in_period: int,
        working_days_in_period: int,
    ) -> Decimal:
        """
        Prorate salary for partial periods (e.g., mid-period hire or termination).
        """
        if working_days_in_period == 0:
            return Decimal("0")
        periods = Decimal(str(PERIODS_PER_YEAR.get(pay_frequency.upper(), 26)))
        full_period_pay = _round(annual_salary / periods)
        daily_rate = _round(full_period_pay / Decimal(str(working_days_in_period)))
        return _round(daily_rate * Decimal(str(days_in_period)))
