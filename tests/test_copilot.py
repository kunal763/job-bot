"""Unit tests for AI Copilot fallback and question answering heuristics."""

import pytest
from pathlib import Path
from job_bot.copilot.llm import AICopilot
from job_bot.vault.profile_vault import ProfileVault


@pytest.fixture
def copilot():
    vault = ProfileVault(Path("profile.json"))
    return AICopilot(vault.profile)


def test_experience_heuristic(copilot):
    ans = copilot.answer_question("How many years of work experience do you have with Python?")
    assert ans == "2"


def test_notice_period_heuristic(copilot):
    ans = copilot.answer_question("What is your official notice period?", options=["Immediate", "15 days", "30 days", "60 days"])
    assert ans == "30 days"


def test_expected_ctc_heuristic(copilot):
    ans = copilot.answer_question("What is your expected CTC (in LPA)?")
    assert ans == str(int(copilot.profile.career.expected_ctc_lpa))


def test_sponsorship_options(copilot):
    ans = copilot.answer_question("Will you require visa sponsorship now or in the future?", options=["Yes", "No"])
    assert ans == "No"


def test_authorized_to_work_options(copilot):
    ans = copilot.answer_question("Are you legally authorized to work in this country?", options=["Yes", "No"])
    assert ans == "Yes"
