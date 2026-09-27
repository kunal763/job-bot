"""Unit tests for candidate profile vault."""

import pytest
from pathlib import Path
from job_bot.vault.profile_vault import ProfileVault


def test_load_sample_profile():
    vault = ProfileVault(Path("profile.json"))
    profile = vault.load()

    assert profile.personal.first_name == "Kunal"
    assert profile.career.total_years_experience == 2.0
    assert profile.career.expected_ctc_lpa >= 12.0
    assert profile.documents.resume_path.exists()


def test_skill_experience_lookup():
    vault = ProfileVault(Path("profile.json"))
    # Python is in user skills
    assert vault.get_skill_experience("Python") == 2.0
    # Fortran is not in user skills
    assert vault.get_skill_experience("Fortran") == 0.0


def test_common_answer_lookup():
    vault = ProfileVault(Path("profile.json"))
    # Sponsorship
    assert vault.get_common_answer("visa sponsorship") == "No"
    # Authorized
    assert vault.get_common_answer("legally authorized to work") == "Yes"
