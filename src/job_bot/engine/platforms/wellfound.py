"""Wellfound (AngelList Talent) Job Search & Application Automation."""

import asyncio
import re
import urllib.parse
from pathlib import Path
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from job_bot.config import config
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.engine.external_filler import ExternalFormFiller
from job_bot.engine.platforms.base import JobPlatform
from job_bot.engine.salary_parser import SalaryParser, evaluate_salary
from job_bot.models import ApplicationStatus, JobListing, UserProfile
from job_bot.utils.logger import logger


class WellfoundPlatform(JobPlatform):
    """Handles startup job discovery and autonomous application on Wellfound (AngelList)."""

    def __init__(
        self,
        page: Page,
        profile: UserProfile,
        copilot: AICopilot,
        repository: JobRepository | None = None,
    ):
        super().__init__(page)
        self.profile = profile
        self.copilot = copilot
        self.repository = repository
        self.answers_log: dict[str, str] = {}

    async def search_jobs(
        self,
        keywords: list[str],
        location: str = "India",
        limit: int = 15,
        easy_apply_only: bool = True,
    ) -> list[JobListing]:
        """Search Wellfound startup jobs and extract matching listings."""
        query_str = " ".join(keywords).lower()
        logger.info(f"Searching Wellfound startup jobs for: '{query_str}' in {location}...")

        # Map common tech keywords to Wellfound standardized role slugs
        role_slug_map = {
            "python": "python-developer",
            "fastapi": "backend-engineer",
            "django": "backend-engineer",
            "backend": "backend-engineer",
            "software": "software-engineer",
            "developer": "software-engineer",
            "fullstack": "full-stack-engineer",
            "full stack": "full-stack-engineer",
            "frontend": "frontend-engineer",
            "devops": "devops-engineer",
            "ai": "machine-learning-engineer",
            "machine learning": "machine-learning-engineer",
            "data": "data-engineer",
            "sre": "site-reliability-engineer",
        }

        matched_slug = None
        for key, slug in role_slug_map.items():
            if key in query_str:
                matched_slug = slug
                break

        search_urls = []
        loc_clean = location.strip().lower()
        if matched_slug:
            if loc_clean and loc_clean != "all":
                search_urls.append(f"https://wellfound.com/role/l/{matched_slug}/{loc_clean}")
                search_urls.append(f"https://wellfound.com/role/l/{matched_slug}/remote-{loc_clean}")
            else:
                search_urls.append(f"https://wellfound.com/role/{matched_slug}")
        else:
            params = {"keywords": query_str}
            if loc_clean and loc_clean != "all":
                params["location"] = loc_clean
            search_urls.append(f"https://wellfound.com/jobs?{urllib.parse.urlencode(params)}")

        listings: list[JobListing] = []
        seen_job_ids = set()

        for search_url in search_urls:
            if len(listings) >= limit:
                break

            logger.info(f"Navigating to Wellfound search: {search_url}")
            try:
                await self.page.goto(search_url, wait_until="domcontentloaded", timeout=35000)
            except Exception as e:
                logger.warning(f"Error loading {search_url}: {e}")
                continue

            await asyncio.sleep(3.0)

            # Check if login or checkpoint is shown
            if "login" in self.page.url or "checkpoint" in self.page.url:
                logger.warning("Wellfound requires authentication for this view. Continuing with public listings...")

            # Auto-scroll if limit is greater than initial view to trigger infinite loading
            if limit > 15:
                prev_count = 0
                for _ in range(min(12, max(1, limit // 10))):
                    curr_count = await self.page.locator('a[href*="/jobs/"]').count()
                    if curr_count >= limit or curr_count == prev_count:
                        break
                    prev_count = curr_count
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(1.5)

            # Extract job links
            job_links = await self.page.locator('a[href*="/jobs/"]').all()
            logger.info(f"Discovered {len(job_links)} raw job links on Wellfound page.")

            for link in job_links:
                if len(listings) >= limit:
                    break

                try:
                    href = await link.get_attribute("href")
                    if not href or "/jobs/" not in href:
                        continue

                    # Canonicalize URL: /jobs/{id}-{slug}
                    full_url = href if href.startswith("http") else f"https://wellfound.com{href}"
                    match = re.search(r"/jobs/(\d+)-", full_url)
                    if not match:
                        continue

                    job_id = match.group(1)
                    if job_id in seen_job_ids:
                        continue
                    seen_job_ids.add(job_id)

                    raw_title = (await link.inner_text()).strip()
                    if not raw_title or len(raw_title) < 2:
                        continue

                    # Extract company card and job card text for metadata
                    company_card = link.locator(
                        'xpath=ancestor::div[contains(@class, "rounded border") or contains(@class, "border-gray-400")][1]'
                    ).first
                    job_card = link.locator(
                        'xpath=ancestor::div[contains(@class, "min-h") or contains(@class, "items-end") or contains(@class, "mb-1")][1]'
                    ).first

                    company_name = "Startup"
                    salary_raw = None
                    card_loc = location

                    if await company_card.count() > 0:
                        card_text = await company_card.inner_text()
                        lines = [line.strip() for line in card_text.split("\n") if line.strip()]
                        if lines and lines[0] != raw_title:
                            company_name = lines[0]

                    # Extract salary and location from specific job card (or fallback to company card)
                    target_for_meta = job_card if await job_card.count() > 0 else company_card
                    if await target_for_meta.count() > 0:
                        meta_text = await target_for_meta.inner_text()
                        meta_lines = [line.strip() for line in meta_text.split("\n") if line.strip()]

                        # Identify salary and equity info
                        for l in meta_lines:
                            if any(sym in l for sym in ["₹", "$", "€", "£"]) and any(
                                t in l.lower() for t in ["lpa", "k", "equity", "no equity", "yr", "year", "–", "-"]
                            ):
                                salary_raw = l
                                break

                        # Identify card location
                        for l in meta_lines:
                            l_lower = l.lower()
                            if any(loc in l_lower for loc in ["pune", "bengaluru", "bangalore", "mumbai", "delhi", "noida", "gurgaon", "gurugram", "hyderabad", "chennai", "india", "remote"]):
                                card_loc = l
                                break
                            elif any(foreign in l_lower for foreign in ["san francisco", "new york", "united states", "london", "canada"]):
                                card_loc = l
                                break

                    job_listing = JobListing(
                        id=f"wellfound_{job_id}",
                        platform="wellfound",
                        external_job_id=job_id,
                        title=raw_title,
                        company=company_name,
                        location=card_loc,
                        salary_raw=salary_raw,
                        url=full_url,
                        easy_apply=True,
                    )
                    listings.append(job_listing)
                except Exception as e:
                    logger.debug(f"Error parsing Wellfound card: {e}")
                    continue

        logger.info(f"Wellfound search complete: extracted {len(listings)} listings.")
        return listings

    async def apply_to_job(self, job: JobListing, dry_run: bool = True) -> tuple[bool, str]:
        """Automates Wellfound application with AI cover note and dry-run safety."""
        logger.info(f"Navigating to Wellfound job: {job.title} at {job.company} ({job.url})")
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            logger.warning(f"Could not load job URL {job.url}: {e}")
            return (False, f"Navigation timeout/error: {e}")

        await asyncio.sleep(2.5)

        # Extract authentic company name directly from the job posting page
        real_company = None
        try:
            page_title = await self.page.title()
            if isinstance(page_title, str):
                m = re.search(r'\bat\s+([^•|]+?)(?:\s*•|\s*\|\s*Wellfound|$)', page_title, re.IGNORECASE)
                if m:
                    cand = m.group(1).strip()
                    if cand and len(cand) > 1 and "wellfound" not in cand.lower():
                        real_company = cand
        except Exception:
            pass

        if not real_company:
            try:
                h1_el = self.page.locator('h1').first
                if await h1_el.count() > 0:
                    h1_text = await h1_el.inner_text()
                    if isinstance(h1_text, str):
                        m_h1 = re.search(r'\bat\s+(.+)$', h1_text.strip(), re.IGNORECASE)
                        if m_h1:
                            cand = m_h1.group(1).strip()
                            if cand and len(cand) > 1:
                                real_company = cand
            except Exception:
                pass

        if not real_company:
            try:
                for a in await self.page.locator('main a[href*="/company/"], a[href*="/company/"]').all():
                    t = await a.inner_text()
                    if isinstance(t, str):
                        t = t.strip()
                        if t and "view" not in t.lower() and "follow" not in t.lower() and len(t) > 1:
                            real_company = t
                            break
            except Exception:
                pass

        if real_company:
            if real_company != job.company:
                logger.info(f"Corrected company name from job page: '{job.company}' -> '{real_company}'")
            job.company = real_company
            if self.repository:
                self.repository.update_job_company(job.id, real_company)

        # Check if already applied specifically on this job listing (ignore global sidebar nav)
        applied_badge = self.page.locator(
            'button[class*="applyButton"]:has-text("Applied"), '
            'button[disabled]:has-text("Applied"), '
            'main button:has-text("Applied"), '
            '[data-test="JobListing"] button:has-text("Applied"), '
            'div[class*="jobListing"] button:has-text("Applied")'
        )
        if await applied_badge.count() > 0 and await applied_badge.first.is_visible():
            return (True, "Already applied previously on Wellfound.")

        # Find Apply button in main content area
        apply_btn = self.page.locator(
            'button[class*="applyButton"]:has-text("Apply"), '
            'main button:has-text("Apply Now"), main button:has-text("Apply"), '
            'button[data-test="JobListing--ApplyButton"], button:has-text("Apply Now"), button:has-text("Apply"), '
            'a:has-text("Apply Now"), a:has-text("Apply")'
        ).first

        try:
            await apply_btn.wait_for(state="visible", timeout=5000)
        except Exception:
            pass

        if await apply_btn.count() == 0 or not await apply_btn.is_visible():
            if await self.page.locator('button[class*="applyButton"]:has-text("Applied"), button[disabled]:has-text("Applied")').count() > 0:
                return (True, "Already applied previously on Wellfound.")
            return (False, "Apply button not found on Wellfound job posting.")

        btn_txt = (await apply_btn.inner_text()).strip()
        if "applied" in btn_txt.lower():
            return (True, "Already applied previously on Wellfound.")

        # Check if button links externally (e.g. Greenhouse, Lever, Ashby)
        href = await apply_btn.get_attribute("href")
        if href and href.startswith("http") and "wellfound.com" not in href:
            logger.info(f"Wellfound job redirects to external ATS: {href}. Launching Universal Form Filler...")
            filler = ExternalFormFiller(self.page, self.profile, self.copilot, self.repository)
            await self.page.goto(href, wait_until="domcontentloaded", timeout=45000)
            return await filler.fill_and_submit(dry_run=dry_run)

        logger.info("Clicking Wellfound 'Apply Now' button...")
        await apply_btn.click()
        await asyncio.sleep(2.0)

        # Locate visible Quick Apply modal
        modal_locator = self.page.locator(
            'div[role="dialog"]:has(button:has-text("Send application")), '
            'div[role="dialog"]:has(button[type="submit"]), '
            'div[role="dialog"]:has(textarea), '
            'form:has(button[data-test*="SubmitButton"]), '
            '[class*="modal"]:has(textarea), '
            'div:has-text("YOUR APPLICATION")'
        )
        modal = None
        for _ in range(6):
            count = await modal_locator.count()
            for i in range(count):
                cand = modal_locator.nth(i)
                if await cand.is_visible():
                    modal = cand
                    break
            if modal:
                break
            await asyncio.sleep(1.0)

        if not modal:
            # Check if a new page/tab opened
            if len(self.page.context.pages) > 1:
                new_tab = self.page.context.pages[-1]
                logger.info(f"External application opened in new tab: {new_tab.url}")
                filler = ExternalFormFiller(new_tab, self.profile, self.copilot, self.repository)
                res = await filler.fill_and_submit(dry_run=dry_run)
                await new_tab.close()
                return res
            return (False, "Wellfound application modal did not appear.")

        logger.info("Wellfound application modal detected. Populating fields...")

        # Check for visa sponsorship / in-country residency blocker banner in the modal
        restriction_banner = modal.locator(
            'div:has-text("does not offer visa sponsorship"), '
            'div:has-text("requires all remote workers to be in-country"), '
            'div:has-text("requires sponsorship"), '
            'div:has-text("require sponsorship")'
        ).first

        if await restriction_banner.count() > 0 and await restriction_banner.is_visible():
            banner_msg = (await restriction_banner.inner_text()).strip().replace("\n", " ")
            logger.warning(f"⚠️ Wellfound application blocked by company policy: {banner_msg}")
            dismiss_btn = modal.locator('button:has-text("Cancel"), button[aria-label="Close"], a:has-text("Cancel")').first
            if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                await dismiss_btn.click()
            return (False, f"Skipped: Visa sponsorship not available / In-country required ({banner_msg[:80]})")

        # Handle location mismatch / relocation prompt if present
        relocate_lbl = modal.locator(
            'label[for*="relocate_to"], '
            'label:has-text("I can relocate to"), '
            'label:has-text("relocate")'
        ).first

        has_location_mismatch = (
            await modal.locator('text="This job does not support the locations on your profile"').count() > 0
            or await modal.locator('text="Update your location preferences"').count() > 0
            or await relocate_lbl.count() > 0
        )

        if has_location_mismatch:
            logger.info("Location preference prompt detected on Wellfound modal.")
            if await relocate_lbl.count() > 0:
                logger.info("Selecting 'I can relocate to...'...")
                await relocate_lbl.click(force=True)
                await asyncio.sleep(0.8)
                self.answers_log["Location Preference"] = "I can relocate to..."

                # Check for react-select or combobox for destination city
                loc_select = modal.locator(
                    '#react-select-form-input--qualification\\.location\\.locationId-input, '
                    'input[id*="qualification.location.locationId"], '
                    '[class*="select__control"], '
                    'div[class*="selectField"]'
                ).first

                if await loc_select.count() > 0 and await loc_select.is_visible():
                    logger.info("Selecting destination city in relocation dropdown...")
                    await loc_select.click(force=True)
                    await asyncio.sleep(0.3)
                    await self.page.keyboard.press("ArrowDown")
                    await asyncio.sleep(0.5)

                    # Check if options dropdown opened
                    menu_opts = self.page.locator('[class*="option"]')
                    opt_count = await menu_opts.count()
                    if opt_count > 0:
                        chosen_opt = menu_opts.first
                        # Prefer option matching job location if possible
                        if job.location:
                            for idx in range(opt_count):
                                opt_elem = menu_opts.nth(idx)
                                opt_text = (await opt_elem.inner_text()).strip()
                                if any(loc_part.strip().lower() in opt_text.lower() for loc_part in job.location.split(",") if loc_part.strip()):
                                    chosen_opt = opt_elem
                                    break
                        opt_label = (await chosen_opt.inner_text()).strip()
                        logger.info(f"Selected relocation destination: {opt_label}")
                        await chosen_opt.click()
                        self.answers_log["Relocation City"] = opt_label
                    else:
                        await self.page.keyboard.press("Enter")
                    await asyncio.sleep(0.8)
            else:
                living_lbl = modal.locator('label[for*="living_in"], label:has-text("I am currently in")').first
                if await living_lbl.count() > 0:
                    logger.info("Selecting 'I am currently in...'...")
                    await living_lbl.click(force=True)
                    await asyncio.sleep(0.8)
                    self.answers_log["Location Preference"] = "I am currently in..."

        # 1. Full Name
        name_inp = modal.locator('#form-input--name, input[name="name"]').first
        if await name_inp.count() > 0 and await name_inp.is_visible():
            val = f"{self.profile.personal.first_name} {self.profile.personal.last_name}"
            await name_inp.fill(val)
            self.answers_log["Full Name"] = val

        # 2. Email Address
        email_inp = modal.locator('#form-input--email, input[name="email"]').first
        if await email_inp.count() > 0 and await email_inp.is_visible():
            val = self.profile.personal.email
            await email_inp.fill(val)
            self.answers_log["Email"] = val

        # 3. Location
        loc_inp = modal.locator('#downshift-0-input, [data-test="Downshift--input"], input[placeholder*="location"]').first
        if await loc_inp.count() > 0 and await loc_inp.is_visible():
            val = self.profile.personal.location
            await loc_inp.fill(val)
            await asyncio.sleep(0.5)
            self.answers_log["Location"] = val

        # 4. Remote Preference Checkbox
        remote_chk = modal.locator('#form-input--remote--true, input[type="checkbox"]:has-text("remote")').first
        if await remote_chk.count() > 0 and await remote_chk.is_visible():
            await remote_chk.check()
            self.answers_log["Remote"] = "Yes"

        # 5. Years of Experience
        yoe_inp = modal.locator('#react-select-form-input--yearsOfExperience-input, input[name="yearsOfExperience"]').first
        if await yoe_inp.count() > 0:
            exp_val = str(int(self.profile.career.total_years_experience or 2))
            await yoe_inp.fill(exp_val)
            await self.page.keyboard.press("Enter")
            self.answers_log["Years of Experience"] = exp_val

        # 6. Desired Salary
        sal_inp = modal.locator('#form-input--desiredSalary, input[name="desiredSalary"]').first
        if await sal_inp.count() > 0 and await sal_inp.is_visible():
            # If USD field, format appropriately (~95,000 USD)
            sal_val = "95000" if "usd" in (await sal_inp.get_attribute("placeholder") or "").lower() else str(int(self.profile.career.expected_ctc_lpa * 100000))
            await sal_inp.fill(sal_val)
            self.answers_log["Desired Salary"] = sal_val

        # 7. Work Authorization & Sponsorship
        us_auth_no = modal.locator('#form-input--usAuthorized--false').first
        if await us_auth_no.count() > 0 and await us_auth_no.is_visible():
            await us_auth_no.check()
            self.answers_log["US Authorized"] = "No"

        # 8. Custom Questions & Cover Note / Pitch to the Hiring Team
        textareas = await modal.locator("textarea").all()
        for idx, textarea in enumerate(textareas):
            if await textarea.is_visible():
                # Wait briefly if element is transitioning / becoming enabled after relocation selection
                for _ in range(10):
                    if not await textarea.is_disabled():
                        break
                    await asyncio.sleep(0.5)

                if await textarea.is_disabled():
                    logger.warning(f"Textarea #{idx+1} remains disabled; skipping.")
                    continue

                # Determine question prompt for this textarea
                question_text = ""
                ancestor_label = textarea.locator("xpath=ancestor::label").first
                if await ancestor_label.count() > 0:
                    raw_lbl = await ancestor_label.inner_text()
                    question_text = raw_lbl.strip().split("\n")[0].strip()
                if not question_text:
                    preceding = textarea.locator("xpath=preceding::div[1]").first
                    if await preceding.count() > 0:
                        question_text = (await preceding.inner_text()).strip()

                if not question_text or len(question_text) < 5 or "form-input" in question_text:
                    question_text = f"Why are you interested in working at {job.company} as {job.title}?"

                logger.info(f"Formulating tailored response via Groq AI Copilot for question: '{question_text}'...")
                skills_str = ", ".join(self.profile.career.skills[:6])
                prompt = (
                    f"Answer this job application question for the company {job.company} and role '{job.title}':\n"
                    f"Question: \"{question_text}\"\n\n"
                    f"Candidate: {self.profile.personal.first_name} {self.profile.personal.last_name}, "
                    f"a software engineer with {self.profile.career.total_years_experience} years of experience specializing in {skills_str}.\n"
                    f"Write an authentic, highly persuasive 2-3 sentence response directly answering the prompt. "
                    f"Do not include placeholders, return only the ready-to-send answer."
                )
                custom_answer = self.copilot.answer_question(
                    question=prompt,
                    job_title=job.title,
                    job_company=job.company,
                )
                if not custom_answer or len(custom_answer) < 20:
                    custom_answer = (
                        f"Hi {job.company} team, I am an engineer specializing in scalable backend systems, Python, "
                        f"and distributed architectures. My experience in performance optimization and microservices "
                        f"aligns directly with the {job.title} role, and I would love to contribute to your technical goals."
                    )
                await textarea.fill(custom_answer)
                self.answers_log[f"Application Answer ({question_text[:30]})"] = custom_answer

        # 9. Resume File Upload
        resume_path = self.profile.documents.resume_path
        if not resume_path.exists():
            for alt in [Path("data/Kunal_Singh_Resume.pdf"), Path("Kunal_Singh_Resume.pdf")]:
                if alt.exists():
                    resume_path = alt.resolve()
                    break

        file_inp = modal.locator('input[type="file"]').first
        if await file_inp.count() > 0 and resume_path.exists():
            logger.info(f"Uploading candidate resume PDF: {resume_path.name}")
            try:
                await file_inp.set_input_files(str(resume_path))
                self.answers_log["Resume Upload"] = resume_path.name
                await asyncio.sleep(1.0)
            except Exception as e:
                logger.debug(f"Resume upload error on Wellfound: {e}")

        # 10. Locate Submit Application button
        submit_btn = modal.locator(
            'button[data-test="QuickApplyModal--SubmitButton"], '
            'button[data-test*="SubmitButton"], '
            'button:has-text("Send application"), '
            'button:has-text("Submit application"), '
            'button[type="submit"]'
        ).first

        if await submit_btn.count() == 0 or not await submit_btn.is_visible():
            return (False, "Submit button not found in Wellfound application modal.")

        # Wait briefly for submit button to enable if form just finished validation
        for _ in range(6):
            if not (await submit_btn.is_disabled() or (await submit_btn.get_attribute("disabled") is not None)):
                break
            await asyncio.sleep(0.5)

        # Check if submit button is truly disabled (e.g. visa sponsorship or in-country requirement)
        is_disabled = await submit_btn.is_disabled() or (await submit_btn.get_attribute("disabled") is not None)
        if is_disabled:
            logger.warning("Submit button is disabled on Wellfound modal (requirements mismatch). Skipping...")
            dismiss_btn = modal.locator('button:has-text("Cancel"), button[aria-label="Close"], a:has-text("Cancel")').first
            if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                await dismiss_btn.click()
            return (False, "Skipped: Wellfound submit button disabled (visa/location requirements mismatch).")

        if dry_run:
            logger.info("🛡️ [DRY RUN] Final Submit button located and verified! Safe review complete.")
            # Safely dismiss modal
            dismiss_btn = self.page.locator('button[aria-label="Close"], button:has-text("Cancel")').first
            if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                await dismiss_btn.click()
            return (True, "Dry-run successful: verified all Wellfound fields and AI note up to Submit.")
        else:
            logger.info("🚀 Clicking Wellfound 'Submit application' button...")
            await submit_btn.scroll_into_view_if_needed()
            await submit_btn.click()
            await asyncio.sleep(4.0)

            # Check confirmation text
            page_text = (await self.page.inner_text("body")).lower()
            if any(term in page_text for term in ["application sent", "applied", "thank you", "successfully submitted"]):
                return (True, "Wellfound application submitted successfully!")
            return (True, "Submit clicked successfully on Wellfound.")
