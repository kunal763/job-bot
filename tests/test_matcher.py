"""Unit tests for JobMatcher scoring and ranking engine."""

import pytest
from pathlib import Path
from job_bot.engine.matcher import JobMatcher
from job_bot.models import (
    CareerDetails,
    EducationDetails,
    PersonalDetails,
    UserProfile,
    VaultDocuments,
)


@pytest.fixture
def test_profile():
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
            skills=["Python", "FastAPI", "C++", "Docker", "AWS"],
        ),
        education=EducationDetails(
            degree="BE",
            field_of_study="Electronics",
            university="AIT Pune",
            graduation_year=2026,
        ),
        documents=VaultDocuments(
            resume_path=Path("data/Kunal_Singh_Resume.pdf"),
        ),
    )


def test_matcher_disqualifies_non_tech_roles(test_profile):
    matcher = JobMatcher(test_profile)
    res_designer = matcher.score_job({"title": "Lead Product Designer", "location": "Bengaluru"})
    assert res_designer.is_disqualified is True
    assert res_designer.total_score == 0

    res_pm = matcher.score_job({"title": "Founding Product Manager", "location": "Remote"})
    assert res_pm.is_disqualified is True

    res_qa = matcher.score_job({"title": "QA Automation Lead", "location": "India"})
    assert res_qa.is_disqualified is True


def test_matcher_disqualifies_us_onsite_without_remote(test_profile):
    matcher = JobMatcher(test_profile)
    res = matcher.score_job({
        "title": "Software Engineer",
        "location": "San Francisco, CA, US",
    })
    assert res.is_disqualified is True
    assert "US onsite" in res.disqualification_reason


def test_matcher_scores_high_for_python_backend_in_india(test_profile):
    matcher = JobMatcher(test_profile)
    res = matcher.score_job({
        "title": "Backend Engineer - Python",
        "location": "Bengaluru, KA, IN",
        "description": "Building high throughput APIs using Python, FastAPI, and Redis.",
        "salary_raw": "₹2M - ₹4M INR",
        "min_lpa": 20.0,
        "max_lpa": 40.0,
    })
    assert res.is_disqualified is False
    assert res.total_score >= 80
    assert any("python" in m for m in res.tech_matches)


def test_matcher_ranks_highest_fit_first(test_profile):
    matcher = JobMatcher(test_profile)
    jobs = [
        {"id": "j1", "title": "Lead Product Designer", "location": "Bengaluru"},
        {"id": "j2", "title": "Software Engineer (India)", "location": "Pune, India", "salary_raw": "₹2.5M - ₹5M INR", "min_lpa": 25.0},
        {"id": "j3", "title": "Backend Engineer - Python", "location": "Bengaluru, India", "salary_raw": "₹2M - ₹4M INR", "min_lpa": 20.0},
    ]
    ranked = matcher.rank_jobs(jobs)
    assert len(ranked) == 2  # Designer filtered out
    assert ranked[0][0]["id"] in ["j2", "j3"]
