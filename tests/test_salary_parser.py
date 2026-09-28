"""Unit tests for salary parsing and 12+ LPA threshold checks."""

import pytest
from job_bot.engine.salary_parser import SalaryParser, evaluate_salary


def test_parse_explicit_lpa_range():
    info = SalaryParser.parse("₹12 - ₹18 LPA")
    assert info is not None
    assert info.min_lpa == 12.0
    assert info.max_lpa == 18.0
    meets, _ = evaluate_salary("₹12 - ₹18 LPA", threshold_lpa=12.0)
    assert meets is True


def test_parse_lacs_single():
    info = SalaryParser.parse("15 Lacs P.A.")
    assert info is not None
    assert info.min_lpa == 15.0
    assert info.max_lpa == 15.0
    meets, _ = evaluate_salary("15 Lacs P.A.", threshold_lpa=12.0)
    assert meets is True


def test_parse_lakhs_below_threshold():
    info = SalaryParser.parse("6 - 9 Lakhs")
    assert info is not None
    assert info.min_lpa == 6.0
    assert info.max_lpa == 9.0
    meets, _ = evaluate_salary("6 - 9 Lakhs", threshold_lpa=12.0)
    assert meets is False  # 9 < 12 LPA


def test_parse_full_inr_numbers():
    info = SalaryParser.parse("₹1,400,000 - ₹2,000,000 a year")
    assert info is not None
    assert info.min_lpa == 14.0
    assert info.max_lpa == 20.0
    meets, _ = evaluate_salary("₹1,400,000 - ₹2,000,000 a year", threshold_lpa=12.0)
    assert meets is True


def test_parse_monthly_rupees():
    # 1.2 Lakh per month -> 14.4 LPA
    info = SalaryParser.parse("₹100000 - ₹150000 / month")
    assert info is not None
    assert info.min_lpa == 12.0
    assert info.max_lpa == 18.0
    meets, _ = evaluate_salary("₹100000 - ₹150000 / month", threshold_lpa=12.0)
    assert meets is True


def test_parse_usd_conversion():
    # $100k - $120k /yr -> converted to LPA (~86 LPA)
    info = SalaryParser.parse("$100,000 - $120,000 /yr")
    assert info is not None
    assert info.min_lpa > 12.0
    assert info.currency == "USD"
    meets, _ = evaluate_salary("$100,000 - $120,000 /yr", threshold_lpa=12.0)
    assert meets is True


def test_unlisted_salary_behavior():
    meets_default, info = evaluate_salary("Not Disclosed", threshold_lpa=12.0, allow_unlisted=False)
    assert meets_default is False

    meets_allowed, _ = evaluate_salary("Not Disclosed", threshold_lpa=12.0, allow_unlisted=True)
    assert meets_allowed is True


def test_parse_inr_millions_and_thousands():
    # YC INR Millions format: ₹2M - ₹4M INR -> 20.0 LPA - 40.0 LPA
    info = SalaryParser.parse("₹2M - ₹4M INR")
    assert info is not None
    assert info.min_lpa == 20.0
    assert info.max_lpa == 40.0
    meets, _ = evaluate_salary("₹2M - ₹4M INR", threshold_lpa=13.0)
    assert meets is True

    # ₹1.5M - ₹4M INR -> 15.0 LPA - 40.0 LPA
    info15 = SalaryParser.parse("₹1.5M - ₹4M INR")
    assert info15 is not None
    assert info15.min_lpa == 15.0
    assert info15.max_lpa == 40.0
    meets15, _ = evaluate_salary("₹1.5M - ₹4M INR", threshold_lpa=13.0)
    assert meets15 is True

    # ₹900K INR -> 9.0 LPA (< 13.0 LPA)
    info_k = SalaryParser.parse("₹900K INR")
    assert info_k is not None
    assert info_k.min_lpa == 9.0
    assert info_k.max_lpa == 9.0
    meets_k, _ = evaluate_salary("₹900K INR", threshold_lpa=13.0)
    assert meets_k is False

