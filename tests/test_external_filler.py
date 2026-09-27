"""Tests for ExternalFormFiller on simulated ATS job application forms."""

import pytest
from playwright.async_api import async_playwright
from job_bot.copilot.llm import AICopilot
from job_bot.engine.external_filler import ExternalFormFiller
from job_bot.vault.profile_vault import ProfileVault


@pytest.mark.asyncio
async def test_external_form_filler_standard_ats():
    """Simulates an external ATS application page (Greenhouse / Lever style)."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head><title>Senior Software Engineer - Application</title></head>
    <body>
        <form id="application-form">
            <div>
                <label for="first_name">First Name</label>
                <input type="text" id="first_name" name="first_name" required>
            </div>
            <div>
                <label for="last_name">Last Name</label>
                <input type="text" id="last_name" name="last_name" required>
            </div>
            <div>
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required>
            </div>
            <div>
                <label for="phone">Phone</label>
                <input type="tel" id="phone" name="phone">
            </div>
            <div>
                <label for="org">Current Company</label>
                <input type="text" id="org" name="org">
            </div>
            <div>
                <label for="urls_linkedin">LinkedIn Profile</label>
                <input type="text" id="urls_linkedin" name="urls[LinkedIn]">
            </div>
            <div>
                <label for="urls_github">GitHub Profile</label>
                <input type="text" id="urls_github" name="urls[GitHub]">
            </div>
            <div>
                <label for="comments">Why are you interested in this role?</label>
                <textarea id="comments" name="comments"></textarea>
            </div>
            <fieldset>
                <legend>Are you legally authorized to work in the country?</legend>
                <label><input type="radio" name="auth" value="Yes"> Yes</label>
                <label><input type="radio" name="auth" value="No"> No</label>
            </fieldset>
            <div>
                <button type="submit" id="submit_app">Submit Application</button>
            </div>
        </form>
    </body>
    </html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        page = await browser.new_page()
        await page.set_content(html_content)

        vault = ProfileVault()
        profile = vault.load()
        copilot = AICopilot(profile)
        filler = ExternalFormFiller(page, profile, copilot)

        success, message = await filler.fill_and_submit(dry_run=True)
        assert success is True
        assert "Dry-run successful" in message

        # Verify input values
        assert await page.locator("#first_name").input_value() == "Kunal"
        assert await page.locator("#last_name").input_value() == "Singh"
        assert await page.locator("#email").input_value() == "ksingh112113114@gmail.com"
        assert "7856902017" in (await page.locator("#phone").input_value())

        assert "linkedin.com" in (await page.locator("#urls_linkedin").input_value())
        assert "github.com" in (await page.locator("#urls_github").input_value())
        
        # Verify AI Copilot generated content in textarea
        comments_val = await page.locator("#comments").input_value()
        assert len(comments_val) > 20

        await browser.close()
