"""Integration test for FormFiller against a simulated Easy Apply form."""

import pytest
from pathlib import Path
from playwright.async_api import async_playwright
from job_bot.copilot.llm import AICopilot
from job_bot.engine.form_filler import FormFiller
from job_bot.vault.profile_vault import ProfileVault


MOCK_FORM_HTML = """
<!DOCTYPE html>
<html>
<head><title>Mock Job Form</title></head>
<body>
    <div id="easy-apply-modal" role="dialog">
        <h2>Easy Apply Test Form</h2>
        
        <!-- Phone number -->
        <div>
            <label for="phoneNumber">Mobile Phone Number</label>
            <input type="tel" id="phoneNumber" />
        </div>

        <!-- Skill experience text input -->
        <div>
            <label for="pyExp">How many years of work experience do you have with Python?</label>
            <input type="number" id="pyExp" />
        </div>

        <!-- Open-ended textarea -->
        <div>
            <label for="summaryText">Briefly describe your experience with scalable backend systems</label>
            <textarea id="summaryText"></textarea>
        </div>

        <!-- Notice period dropdown -->
        <div>
            <label for="noticeSelect">What is your notice period?</label>
            <select id="noticeSelect">
                <option value="">Select an option</option>
                <option value="15">15 days</option>
                <option value="30">30 days</option>
                <option value="60">60 days</option>
            </select>
        </div>

        <!-- Radio group for work authorization -->
        <fieldset id="authFieldset">
            <legend>Are you legally authorized to work in this country?</legend>
            <label><input type="radio" name="authorized" value="yes" /> Yes</label>
            <label><input type="radio" name="authorized" value="no" /> No</label>
        </fieldset>

        <!-- Resume File Upload -->
        <div>
            <label for="resumeUpload">Upload Resume</label>
            <input type="file" id="resumeUpload" />
        </div>
    </div>
</body>
</html>
"""


@pytest.mark.asyncio
async def test_form_filler_fills_all_fields(tmp_path):
    # Write mock HTML to file
    html_file = tmp_path / "mock_apply.html"
    html_file.write_text(MOCK_FORM_HTML, encoding="utf-8")

    vault = ProfileVault(Path("profile.json"))
    profile = vault.load()
    copilot = AICopilot(profile)

    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        page = await browser.new_page()
        await page.goto(f"file://{html_file.resolve()}")

        modal = page.locator("#easy-apply-modal")
        filler = FormFiller(page, profile, copilot, repository=None)

        answers = await filler.fill_current_step(modal, job_title="Python Engineer", job_company="TestCo")

        # Verify values in DOM
        phone_val = await page.locator("#phoneNumber").input_value()
        exp_val = await page.locator("#pyExp").input_value()
        summary_val = await page.locator("#summaryText").input_value()
        select_val = await page.locator("#noticeSelect").input_value()
        radio_checked = await page.locator('input[name="authorized"][value="yes"]').is_checked()

        assert exp_val == "2"  # 2 years experience with Python
        assert summary_val != ""  # Filled summary
        assert select_val == "30"  # Selected 30 days notice
        assert radio_checked is True  # Authorized to work = Yes
        assert "Resume Upload" in answers

        await browser.close()
