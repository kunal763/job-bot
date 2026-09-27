"""Unit tests for SQLite repository and deduplication."""

import pytest
from pathlib import Path
from job_bot.db.repository import JobRepository
from job_bot.models import ApplicationStatus, JobListing, SalaryInfo


@pytest.fixture
def temp_repo(tmp_path):
    db_file = tmp_path / "test_jobs.db"
    return JobRepository(db_path=db_file)


def test_save_and_deduplicate(temp_repo):
    job = JobListing(
        id="linkedin_123456",
        platform="linkedin",
        external_job_id="123456",
        title="Senior Python Backend Engineer",
        company="TechCorp",
        location="Bengaluru",
        salary_raw="15 - 20 LPA",
        salary_info=SalaryInfo(raw_text="15 - 20 LPA", min_lpa=15.0, max_lpa=20.0),
        url="https://linkedin.com/jobs/view/123456",
        easy_apply=True,
    )

    assert temp_repo.is_job_processed("linkedin_123456") is False

    temp_repo.save_job(job, initial_status=ApplicationStatus.QUEUED)
    assert temp_repo.is_job_processed("linkedin_123456") is True

    # Test status update
    temp_repo.update_application_status(
        job_id="linkedin_123456",
        status=ApplicationStatus.APPLIED,
        notes="Applied via easy apply",
    )

    apps = temp_repo.get_applications(status=ApplicationStatus.APPLIED)
    assert len(apps) == 1
    assert apps[0]["title"] == "Senior Python Backend Engineer"
    assert apps[0]["status"] == "APPLIED"


def test_qa_cache(temp_repo):
    question = "How many years of experience do you have with Kubernetes?"
    answer = "4.5"

    assert temp_repo.get_cached_answer(question) is None

    temp_repo.cache_answer(question, answer, source="test")
    # Same question with slight punctuation difference
    query_variant = "How many years of experience do you have with Kubernetes ?"
    assert temp_repo.get_cached_answer(query_variant) == "4.5"
