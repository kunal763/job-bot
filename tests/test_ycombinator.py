"""Unit tests for Y Combinator (Work at a Startup) platform integration."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from job_bot.engine.platforms.ycombinator import YCombinatorPlatform
from job_bot.models import (
    ApplicationStatus,
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
            portfolio_url="http://kunal763.github.io/",
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


def test_yc_platform_initialization(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = MagicMock()
    platform = YCombinatorPlatform(
        page=mock_page,
        profile=sample_profile,
        copilot=mock_copilot,
    )
    assert platform.profile.personal.first_name == "Kunal"
    assert platform.profile.personal.portfolio_url == "http://kunal763.github.io/"
    assert platform.answers_log == {}


@pytest.mark.asyncio
async def test_yc_search_jobs_parsing(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = MagicMock()
    platform = YCombinatorPlatform(mock_page, sample_profile, mock_copilot)

    # Mock evaluate returning cards
    mock_page.evaluate = AsyncMock(return_value=[
        {
            "href": "/jobs/13302",
            "company": "Mason",
            "tagline": "Mason is the fastest way to take smart devices from idea to end user",
            "title": "Software Engineer - Backend",
            "details": "Full-time · Seattle, WA · $80K - $140K",
        },
        {
            "href": "/jobs/20001",
            "company": "Rivia.AI",
            "tagline": "Interactive Product Demos",
            "title": "Backend Engineer - Python",
            "details": "Full-time · Bengaluru, KA, IN · ₹2M - ₹4M INR",
        },
        {
            "href": "/jobs/30002",
            "company": "Intelligence Factory",
            "tagline": "Human Intelligence for Robots",
            "title": "Data Engineer (India)",
            "details": "Full-time · Pune, Maharashtra, IN · ₹1.5M - ₹4M INR",
        },
    ])

    mock_inp = AsyncMock()
    mock_locator = MagicMock()
    mock_locator.first = mock_inp
    mock_page.locator = MagicMock(return_value=mock_locator)

    listings = await platform.search_jobs(keywords=["Python"], location="India", limit=5)

    assert len(listings) == 3
    # Check Mason
    assert listings[0].id == "yc_13302"
    assert listings[0].company == "Mason"
    assert listings[0].title == "Software Engineer - Backend"
    assert listings[0].salary_raw == "$80K - $140K"
    assert listings[0].salary_info is not None and listings[0].salary_info.min_lpa > 50.0

    # Check Rivia.AI
    assert listings[1].id == "yc_20001"
    assert listings[1].company == "Rivia.AI"
    assert listings[1].title == "Backend Engineer - Python"
    assert listings[1].salary_raw == "₹2M - ₹4M INR"
    assert listings[1].salary_info.min_lpa == 20.0
    assert listings[1].salary_info.max_lpa == 40.0

    # Check Intelligence Factory in Pune
    assert listings[2].id == "yc_30002"
    assert listings[2].company == "Intelligence Factory"
    assert listings[2].location == "Pune, Maharashtra, IN"
    assert listings[2].salary_raw == "₹1.5M - ₹4M INR"
    assert listings[2].salary_info.min_lpa == 15.0
    assert listings[2].salary_info.max_lpa == 40.0


@pytest.mark.asyncio
async def test_yc_apply_already_applied(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = MagicMock()
    platform = YCombinatorPlatform(mock_page, sample_profile, mock_copilot)

    mock_badge = AsyncMock()
    mock_badge.count.return_value = 1
    mock_nth = AsyncMock()
    mock_nth.is_visible.return_value = True
    mock_badge.nth.return_value = mock_nth
    mock_page.locator = MagicMock(return_value=mock_badge)

    job = JobListing(
        id="yc_13302",
        platform="yc",
        external_job_id="13302",
        title="Software Engineer - Backend",
        company="Mason",
        url="https://www.workatastartup.com/jobs/13302",
    )

    success, msg = await platform.apply_to_job(job, dry_run=True)
    assert success is True
    assert "Already applied" in msg


@pytest.mark.asyncio
async def test_yc_apply_dry_run_generates_pitch(sample_profile):
    mock_page = AsyncMock()
    mock_copilot = AsyncMock()
    mock_copilot.generate_note.return_value = "Hi Founders, I have 2 years of Python and FastAPI experience."
    platform = YCombinatorPlatform(mock_page, sample_profile, mock_copilot)

    # Mock page title
    mock_page.title = AsyncMock(return_value="Backend Engineer at Rivia.AI | Y Combinator's Work at a Startup")

    # Mock locators
    def mock_loc_side_effect(selector):
        loc = AsyncMock()
        if "Applied" in selector:
            loc.count.return_value = 0
            return loc
        elif "Apply to this role" in selector or "Apply" in selector:
            loc.count.return_value = 1
            loc.first = AsyncMock()
            loc.first.is_visible = AsyncMock(return_value=True)
            loc.first.get_attribute = AsyncMock(return_value="https://account.ycombinator.com/authenticate?continue=https://www.workatastartup.com/application?signup_job_id=20001")
            return loc
        loc.count.return_value = 0
        return loc

    mock_page.locator = MagicMock(side_effect=mock_loc_side_effect)

    job = JobListing(
        id="yc_20001",
        platform="yc",
        external_job_id="20001",
        title="Backend Engineer - Python",
        company="Rivia.AI",
        url="https://www.workatastartup.com/jobs/20001",
    )

    success, msg = await platform.apply_to_job(job, dry_run=True)
    assert success is True
    assert "Dry-run successful" in msg
    mock_copilot.generate_note.assert_called_once()


@pytest.mark.asyncio
async def test_yc_apply_multi_field_modal(sample_profile):
    mock_page = AsyncMock()
    mock_page.url = "https://www.workatastartup.com/jobs/103118"
    mock_copilot = MagicMock()
    mock_copilot.generate_note = AsyncMock(return_value="I cut C++ latency from 12us to 4us and built RAG pipelines for 35k+ pages.")
    mock_copilot.answer_question.side_effect = lambda question="", **kw: f"Answer for: {question}. I bring proven competitive grit and technical depth."
    platform = YCombinatorPlatform(mock_page, sample_profile, mock_copilot)

    mock_page.title = AsyncMock(return_value="Founding Research Engineer at Uplift AI | Y Combinator")

    # Mock 3 textareas
    mock_ta0 = AsyncMock()
    mock_ta0.is_visible.return_value = True
    mock_ta0.input_value.return_value = ""
    mock_ta0.evaluate.return_value = "Reach out to the team at Uplift AI"

    mock_ta1 = AsyncMock()
    mock_ta1.is_visible.return_value = True
    mock_ta1.input_value.return_value = ""
    mock_ta1.evaluate.return_value = "What is one impressive non-tech thing you have accomplished *"

    mock_ta2 = AsyncMock()
    mock_ta2.is_visible.return_value = True
    mock_ta2.input_value.return_value = ""
    mock_ta2.evaluate.return_value = "If a VC gives you $3M today, what will you build? Share 2 ideas *"

    mock_textareas_loc = MagicMock()
    mock_textareas_loc.all = AsyncMock(return_value=[mock_ta0, mock_ta1, mock_ta2])

    # Mock locators
    def mock_loc_side_effect(selector):
        loc = AsyncMock()
        if "Applied" in selector:
            loc.count.return_value = 0
            return loc
        elif "Apply to this role" in selector or "Apply" in selector:
            loc.count.return_value = 1
            loc.first = AsyncMock()
            loc.first.is_visible = AsyncMock(return_value=True)
            loc.first.get_attribute = AsyncMock(return_value="https://www.workatastartup.com/application?signup_job_id=103118")
            return loc
        elif "textarea" in selector:
            return mock_textareas_loc
        elif "input" in selector:
            loc.all = AsyncMock(return_value=[])
            return loc
        elif "button:has-text" in selector:
            mock_btn = AsyncMock()
            mock_btn.count.return_value = 1
            mock_btn.is_visible.return_value = True
            mock_btn.is_enabled.return_value = True
            loc.first = mock_btn
            return loc
        loc.count.return_value = 0
        return loc

    mock_page.locator = MagicMock(side_effect=mock_loc_side_effect)

    job = JobListing(
        id="yc_103118",
        platform="yc",
        external_job_id="103118",
        title="Founding Research Engineer",
        company="Uplift AI",
        url="https://www.workatastartup.com/jobs/103118",
    )

    success, msg = await platform.apply_to_job(job, dry_run=True)
    assert success is True
    assert "Dry-run successful" in msg
    mock_copilot.generate_note.assert_called_once()
    assert mock_copilot.answer_question.call_count == 2
    assert "Pitch to Founders" in platform.answers_log
    assert len(platform.answers_log) == 3

