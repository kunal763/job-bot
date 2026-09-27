"""Unit tests for Wellfound (AngelList) platform integration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from job_bot.engine.platforms.wellfound import WellfoundPlatform
from job_bot.models import (
    JobListing,
    UserProfile,
    PersonalDetails,
    CareerDetails,
    EducationDetails,
    VaultDocuments,
)


@pytest.fixture
def sample_profile():
    return UserProfile(
        personal=PersonalDetails(
            first_name="Kunal",
            last_name="Singh",
            email="ksingh112113114@gmail.com",
            phone="+917856902017",
            location="Pune, India",
        ),
        career=CareerDetails(
            current_title="Software Developer",
            total_years_experience=2.0,
            current_ctc_lpa=9.0,
            expected_ctc_lpa=15.0,
            notice_period_days=30,
            skills=["Python", "FastAPI", "Docker", "AWS"],
        ),
        education=EducationDetails(
            degree="B.Tech",
            field_of_study="Computer Science",
            university="MIT",
            graduation_year=2024,
        ),
        documents=VaultDocuments(
            resume_path=Path("data/Kunal_Singh_Resume.pdf"),
        ),
    )


def test_wellfound_platform_initialization(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = MagicMock()
    platform = WellfoundPlatform(
        page=mock_page,
        profile=sample_profile,
        copilot=mock_copilot,
    )
    assert platform.profile.personal.first_name == "Kunal"
    assert platform.answers_log == {}


@pytest.mark.asyncio
async def test_wellfound_apply_already_applied(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = MagicMock()
    platform = WellfoundPlatform(mock_page, sample_profile, mock_copilot)

    # Mock applied badge is visible
    mock_badge = AsyncMock()
    mock_badge.count.return_value = 1
    mock_first = AsyncMock()
    mock_first.is_visible.return_value = True
    mock_badge.first = mock_first
    mock_page.locator = MagicMock(return_value=mock_badge)

    job = JobListing(
        id="wellfound_12345",
        platform="wellfound",
        external_job_id="12345",
        title="Python Developer",
        company="Startup Co",
        url="https://wellfound.com/jobs/12345-python-developer",
    )

    success, msg = await platform.apply_to_job(job, dry_run=True)
    assert success is True
    assert "Already applied" in msg
