"""Pydantic data models for Job Bot."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from pydantic import BaseModel, EmailStr, Field


class ApplicationStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    FILTERED_OUT = "FILTERED_OUT"
    QUEUED = "QUEUED"
    APPLIED = "APPLIED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    REVIEW_NEEDED = "REVIEW_NEEDED"


class SalaryInfo(BaseModel):
    """Normalized salary information."""
    raw_text: str
    min_lpa: float | None = None
    max_lpa: float | None = None
    currency: str = "INR"
    period: str = "annual"  # annual, monthly, hourly
    is_estimated: bool = False

    def meets_threshold(self, threshold_lpa: float, allow_unlisted: bool = False) -> bool:
        """Evaluate if the salary meets the minimum threshold in LPA."""
        if self.max_lpa is not None:
            return self.max_lpa >= threshold_lpa
        if self.min_lpa is not None:
            return self.min_lpa >= threshold_lpa
        return allow_unlisted


class JobListing(BaseModel):
    """Job listing extracted from a job platform."""
    id: str  # Format: {platform}_{external_job_id}
    platform: str = "linkedin"
    external_job_id: str
    title: str
    company: str
    location: str | None = None
    salary_raw: str | None = None
    salary_info: SalaryInfo | None = None
    url: str
    description: str | None = None
    easy_apply: bool = True
    scraped_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApplicationRecord(BaseModel):
    """Database record tracking the state of an application."""
    job_id: str
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    applied_at: datetime | None = None
    notes: str | None = None
    error_message: str | None = None
    custom_answers: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PersonalDetails(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    location: str = "India"
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None


class CareerDetails(BaseModel):
    current_title: str
    total_years_experience: float
    notice_period_days: int = 30
    current_ctc_lpa: float | None = None
    expected_ctc_lpa: float
    skills: list[str] = Field(default_factory=list)
    summary: str | None = None


class EducationDetails(BaseModel):
    degree: str
    field_of_study: str
    university: str
    graduation_year: int
    gpa_or_percentage: str | None = None


class VaultDocuments(BaseModel):
    resume_path: Path
    cover_letter_path: Path | None = None


class UserProfile(BaseModel):
    """Complete profile vault representation."""
    personal: PersonalDetails
    career: CareerDetails
    education: EducationDetails
    documents: VaultDocuments
    common_answers: dict[str, str] = Field(
        default_factory=lambda: {
            "sponsorship": "No",
            "authorized_to_work": "Yes",
            "willing_to_relocate": "Yes",
            "gender": "Decline to identify",
            "disability": "Decline to answer",
            "veteran": "Decline to answer",
        }
    )
