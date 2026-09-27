"""Salary normalization and threshold evaluation engine.

Extracts salary ranges from various text formats (LPA, Lakhs, INR, Monthly, USD)
and normalizes them into annual Lakhs Per Annum (LPA) for strict threshold checks.
"""

import re
from job_bot.models import SalaryInfo

USD_TO_INR_RATE = 86.0  # approximate conversion for USD listings


class SalaryParser:
    """Robust parser for messy salary strings."""

    @classmethod
    def parse(cls, raw: str | None) -> SalaryInfo | None:
        if not raw or not raw.strip():
            return None

        clean_text = raw.strip()
        lowered = clean_text.lower()

        # Check for unlisted / not disclosed
        if any(term in lowered for term in ["not disclosed", "competitive", "undisclosed", "as per industry"]):
            return SalaryInfo(raw_text=clean_text, min_lpa=None, max_lpa=None, is_estimated=False)

        # 1. USD salary patterns: e.g. $100,000 - $140,000 /yr or $120k
        if "$" in clean_text or "usd" in lowered:
            return cls._parse_usd(clean_text)

        # 2. Lakhs / LPA patterns: e.g. "12 - 18 LPA", "12-15 Lacs P.A.", "15 Lakhs", "12.5 to 16.0 LPA", "15L - 20L"
        lpa_match = cls._parse_lpa_explicit(clean_text)
        if lpa_match:
            return lpa_match

        # 3. Monthly Rupee amounts: e.g. "₹1,00,000 - ₹1,50,000 / month", "80k - 120k / month"
        if any(m in lowered for m in ["month", "/mo", "per month", "p.m."]):
            return cls._parse_monthly(clean_text)

        # 4. Full Rupee figures: e.g. "₹12,00,000 - ₹18,00,000 / yr" or "1200000 - 1800000"
        full_match = cls._parse_full_inr(clean_text)
        if full_match:
            return full_match

        # Fallback: couldn't confidently parse
        return SalaryInfo(raw_text=clean_text, min_lpa=None, max_lpa=None)

    @classmethod
    def _parse_lpa_explicit(cls, text: str) -> SalaryInfo | None:
        """Parse strings like '12 - 18 LPA', '14.5 Lacs', '12L - 18L'."""
        pattern = re.compile(
            r"([₹\s]*)(?P<min>\d+(?:\.\d+)?)\s*(?:-|to|–)\s*([₹\s]*)(?P<max>\d+(?:\.\d+)?)\s*(?:lpa|lacs?|lakhs?|l\b)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            min_val = float(match.group("min"))
            max_val = float(match.group("max"))
            return SalaryInfo(raw_text=text, min_lpa=min_val, max_lpa=max_val, period="annual")

        # Single value e.g. "15 LPA", "14 Lakhs", "16.5L"
        single_pattern = re.compile(
            r"([₹\s]*)(?P<val>\d+(?:\.\d+)?)\s*(?:lpa|lacs?|lakhs?|l\b)",
            re.IGNORECASE,
        )
        single_match = single_pattern.search(text)
        if single_match:
            val = float(single_match.group("val"))
            return SalaryInfo(raw_text=text, min_lpa=val, max_lpa=val, period="annual")

        return None

    @classmethod
    def _parse_monthly(cls, text: str) -> SalaryInfo | None:
        """Parse monthly figures and convert to annual LPA."""
        # Clean commas and symbols
        cleaned = text.replace(",", "").replace("₹", "").strip()
        
        # Monthly ranges: e.g. "₹100000 - ₹150000 / month" or "80k - 120k / month"
        range_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)", cleaned)
        if range_match:
            min_monthly = float(range_match.group(1))
            max_monthly = float(range_match.group(2))
            # If values are in 'k' (e.g. 80 - 120 k)
            if "k" in text.lower() and min_monthly < 1000:
                min_monthly *= 1000
                max_monthly *= 1000
            min_lpa = (min_monthly * 12) / 100_000
            max_lpa = (max_monthly * 12) / 100_000
            return SalaryInfo(raw_text=text, min_lpa=round(min_lpa, 2), max_lpa=round(max_lpa, 2), period="monthly")

        # Single monthly figure
        single_match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if single_match:
            monthly = float(single_match.group(1))
            if "k" in text.lower() and monthly < 1000:
                monthly *= 1000
            lpa = (monthly * 12) / 100_000
            return SalaryInfo(raw_text=text, min_lpa=round(lpa, 2), max_lpa=round(lpa, 2), period="monthly")

        return None

    @classmethod
    def _parse_full_inr(cls, text: str) -> SalaryInfo | None:
        """Parse full amounts e.g. '₹12,00,000 - ₹18,00,000 a year'."""
        cleaned = text.replace(",", "").replace("₹", "").replace("INR", "").replace("inr", "")
        # Range of numbers >= 100,000
        matches = re.findall(r"\b(\d{6,8})\b", cleaned)
        if len(matches) >= 2:
            min_val = float(matches[0]) / 100_000
            max_val = float(matches[1]) / 100_000
            return SalaryInfo(raw_text=text, min_lpa=round(min_val, 2), max_lpa=round(max_val, 2), period="annual")
        elif len(matches) == 1:
            val = float(matches[0]) / 100_000
            return SalaryInfo(raw_text=text, min_lpa=round(val, 2), max_lpa=round(val, 2), period="annual")

        return None

    @classmethod
    def _parse_usd(cls, text: str) -> SalaryInfo | None:
        """Parse USD amounts e.g. '$100,000 - $150,000' or '$120k'."""
        cleaned = text.replace(",", "").replace("$", "").lower()
        k_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*k?\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*k")
        k_match = k_pattern.search(cleaned)
        if k_match:
            min_k = float(k_match.group(1))
            max_k = float(k_match.group(2))
            min_usd = min_k * 1000 if min_k < 1000 else min_k
            max_usd = max_k * 1000 if max_k < 1000 else max_k
            min_lpa = (min_usd * USD_TO_INR_RATE) / 100_000
            max_lpa = (max_usd * USD_TO_INR_RATE) / 100_000
            return SalaryInfo(
                raw_text=text,
                min_lpa=round(min_lpa, 2),
                max_lpa=round(max_lpa, 2),
                currency="USD",
                period="annual",
                is_estimated=True,
            )
        
        matches = re.findall(r"\b(\d{4,7})\b", cleaned)
        if len(matches) >= 2:
            min_usd = float(matches[0])
            max_usd = float(matches[1])
            min_lpa = (min_usd * USD_TO_INR_RATE) / 100_000
            max_lpa = (max_usd * USD_TO_INR_RATE) / 100_000
            return SalaryInfo(
                raw_text=text,
                min_lpa=round(min_lpa, 2),
                max_lpa=round(max_lpa, 2),
                currency="USD",
                period="annual",
                is_estimated=True,
            )

        return None


def evaluate_salary(
    salary_raw: str | None,
    threshold_lpa: float = 12.0,
    allow_unlisted: bool = False,
) -> tuple[bool, SalaryInfo | None]:
    """Evaluates whether a salary raw string meets the threshold.

    Returns:
        (meets_criteria: bool, parsed_info: SalaryInfo | None)
    """
    if not salary_raw:
        return (allow_unlisted, None)

    info = SalaryParser.parse(salary_raw)
    if not info or (info.min_lpa is None and info.max_lpa is None):
        return (allow_unlisted, info)

    meets = info.meets_threshold(threshold_lpa, allow_unlisted=allow_unlisted)
    return (meets, info)
