"""LinkedIn Job Search & Easy Apply Automation."""

import asyncio
import urllib.parse
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
from job_bot.config import config
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.engine.form_filler import FormFiller
from job_bot.engine.platforms.base import JobPlatform
from job_bot.engine.salary_parser import SalaryParser, evaluate_salary
from job_bot.models import ApplicationStatus, JobListing, UserProfile
from job_bot.utils.logger import logger


class LinkedInPlatform(JobPlatform):
    """Handles job discovery and Easy Apply automation on LinkedIn."""

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
        self.form_filler = FormFiller(page, profile, copilot, repository)

    async def search_jobs(
        self,
        keywords: list[str],
        location: str = "India",
        limit: int = 15,
        easy_apply_only: bool = True,
    ) -> list[JobListing]:
        """Search LinkedIn jobs and parse matching cards."""
        query_str = " ".join(keywords)
        params = {
            "keywords": query_str,
            "sortBy": "DD",  # Most recent
        }
        if location and location.strip():
            params["location"] = location.strip()
        if easy_apply_only:
            params["f_AL"] = "true"  # Easy Apply filter

        search_url = f"https://www.linkedin.com/jobs/search/?{urllib.parse.urlencode(params)}"
        logger.info(f"Navigating to LinkedIn search: {search_url}")

        try:
            await self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            logger.warning(f"Direct search navigation encountered: {e}. Recovering via jobs home...")
            await self.page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1.5)
            await self.page.goto(search_url, wait_until="domcontentloaded", timeout=45000)

        await asyncio.sleep(3.0)

        # Check if login prompt or checkpoint is shown
        if "login" in self.page.url or "checkpoint" in self.page.url:
            logger.warning(
                "LinkedIn requires login! Please log in once in non-headless mode to save the session."
            )

        listings: list[JobListing] = []

        # Find job cards
        card_selectors = [
            ".job-card-container",
            "li.jobs-search-results__list-item",
            "div.job-search-card",
            "div.base-card",
        ]

        cards_locator = None
        for sel in card_selectors:
            loc = self.page.locator(sel)
            if await loc.count() > 0:
                cards_locator = loc
                break

        if not cards_locator:
            logger.warning("No job cards found on current page.")
            return listings

        count = await cards_locator.count()
        logger.info(f"Found {count} job cards on current search page.")

        for i in range(min(count, limit)):
            try:
                card = cards_locator.nth(i)
                await card.scroll_into_view_if_needed()
                await asyncio.sleep(0.2)

                import re
                job_id = None

                # 1. Check data-entity-urn first (e.g. urn:li:jobPosting:4463253082)
                entity_urn = await card.get_attribute("data-entity-urn")
                if entity_urn:
                    m = re.search(r"(\d{8,12})", entity_urn)
                    if m:
                        job_id = m.group(1)

                # 2. Check data attributes
                if not job_id:
                    for attr in ["data-job-id", "data-occludable-job-id"]:
                        val = await card.get_attribute(attr)
                        if val:
                            m = re.search(r"(\d{8,12})", val)
                            if m:
                                job_id = m.group(1)
                                break

                # 3. Extract direct job link and job ID from primary links
                link_elem = card.locator("a.base-card__full-link, a.job-card-list__title--link, a[href*='/jobs/view/']").first
                href = await link_elem.get_attribute("href") if await link_elem.count() > 0 else ""

                if not job_id and href:
                    m = re.search(r"(\d{8,12})", href)
                    if m:
                        job_id = m.group(1)

                # 4. Fallback: check all anchors in card
                if not job_id:
                    all_anchors = await card.locator("a[href]").all()
                    for a in all_anchors:
                        h = await a.get_attribute("href") or ""
                        m = re.search(r"(\d{8,12})", h)
                        if m:
                            job_id = m.group(1)
                            href = h
                            break

                title_elem = card.locator("h3.base-search-card__title, .job-card-list__title--link, a.base-card__full-link .sr-only").first
                raw_title = (await title_elem.inner_text()).strip() if await title_elem.count() > 0 else "Software Engineer"
                title = raw_title.split("\n")[0].strip()

                company_elem = card.locator("h4.base-search-card__subtitle, .job-card-container__primary-description, a[data-tracking-control-name*='job_search_card_subtitle']").first
                raw_company = (await company_elem.inner_text()).strip() if await company_elem.count() > 0 else "Unknown Company"
                company = raw_company.split("\n")[0].strip()

                loc_elem = card.locator(".job-search-card__location, .job-card-container__metadata-item").first
                raw_loc = (await loc_elem.inner_text()).strip() if await loc_elem.count() > 0 else (location or "India")
                loc_text = raw_loc.split("\n")[0].strip()

                if not job_id:
                    import hashlib
                    job_id = hashlib.md5(f"{title}_{company}".encode()).hexdigest()[:10]

                job_url = f"https://www.linkedin.com/jobs/view/{job_id}/" if str(job_id).isdigit() else (href.split("?")[0] if href else search_url)

                # Check salary text in metadata
                meta_text = await card.inner_text()
                salary_info = SalaryParser.parse(meta_text)
                salary_raw = salary_info.raw_text if (salary_info and salary_info.raw_text != meta_text) else None

                job_listing = JobListing(
                    id=f"linkedin_{job_id}",
                    platform="linkedin",
                    external_job_id=str(job_id),
                    title=title,
                    company=company,
                    location=loc_text,
                    salary_raw=salary_raw,
                    salary_info=salary_info,
                    url=job_url,
                    easy_apply=easy_apply_only,
                )
                listings.append(job_listing)
            except Exception as e:
                logger.debug(f"Error parsing card {i}: {e}")
                continue

        return listings

    async def apply_to_job(self, job: JobListing, dry_run: bool = True) -> tuple[bool, str]:
        """Automates LinkedIn Easy Apply flow with dry-run protection."""
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=35000)
        except Exception as e:
            logger.warning(f"Could not load job URL {job.url}: {e}")
            return (False, f"Navigation timeout/error: {e}")
        await asyncio.sleep(2.5)

        # 1. First check if already applied
        applied_badge = self.page.locator('span:has-text("Applied"), .artdeco-inline-feedback--success')
        if await applied_badge.count() > 0:
            return (True, "Already applied previously.")

        # 2. Check for Easy Apply button specifically
        easy_apply_btn = self.page.locator(
            'button:has-text("Easy Apply"), button[aria-label*="Easy Apply"], button:has-text("تقديم سهل")'
        ).first

        try:
            await easy_apply_btn.wait_for(state="visible", timeout=4000)
        except Exception:
            pass

        # 3. If NOT Easy Apply, look for External Apply button
        if await easy_apply_btn.count() == 0 or not await easy_apply_btn.is_visible():
            ext_btn = self.page.locator(
                'button:has-text("Apply on company website"), a:has-text("Apply on company website"), '
                'button.jobs-apply-button, a.jobs-apply-button, .jobs-s-apply a, .jobs-s-apply button, '
                'button:has-text("Apply"), a:has-text("Apply")'
            ).first
            if await ext_btn.count() > 0 and await ext_btn.is_visible():
                logger.info("Found external company apply button. Launching Universal AI Form Filler...")
                new_page = None
                try:
                    try:
                        async with self.page.context.expect_page(timeout=5000) as new_page_info:
                            await ext_btn.click()
                        new_page = await new_page_info.value
                    except Exception:
                        pass

                    target_page = new_page if new_page else self.page
                    await asyncio.sleep(2.0)

                    # Handle LinkedIn redirection interstitial ("safety/go")
                    if "safety/go" in target_page.url:
                        logger.info("Waiting for LinkedIn external safety redirect...")
                        try:
                            await target_page.wait_for_url(lambda u: "safety/go" not in u, timeout=12000)
                        except Exception:
                            pass

                    from job_bot.engine.external_filler import ExternalFormFiller
                    filler = ExternalFormFiller(target_page, self.profile, self.copilot, self.repository)
                    res = await filler.fill_and_submit(dry_run=dry_run)
                    if new_page:
                        try:
                            await new_page.close()
                        except Exception:
                            pass
                    return res
                except Exception as e:
                    logger.warning(f"External application error: {e}")
                    return (False, f"External application error: {e}")

            msg = "Neither Easy Apply nor external company apply button was found on job posting."
            logger.warning(msg)
            return (False, msg)

        logger.info("Clicking 'Easy Apply' button...")
        await easy_apply_btn.click()
        
        # Wait for modal dialog or unified container to appear
        modal_selector = 'div.jobs-easy-apply-modal, div[role="dialog"], form.jobs-easy-apply-form, div:has(button[data-view-name*="unify"])'
        try:
            await self.page.locator(modal_selector).first.wait_for(state="visible", timeout=6000)
        except Exception:
            pass
        await asyncio.sleep(1.5)

        # Modal / Form container locator (dialogs prioritized over general containers)
        modal_priority_selector = (
            'div.jobs-easy-apply-modal, div[role="dialog"], form.jobs-easy-apply-form, '
            'div:has(button[data-view-name*="unify"]), form, main, body'
        )
        modal = self.page.locator(modal_priority_selector).first
        if await modal.count() == 0:
            msg = "Easy Apply application form did not appear."
            logger.error(msg)
            return (False, msg)

        max_steps = 10
        current_step = 0

        while current_step < max_steps:
            current_step += 1
            logger.info(f"Processing application step {current_step}...")
            await asyncio.sleep(1.0)

            # Re-locate active form container on current step
            modal = self.page.locator(modal_priority_selector).first

            # 1. Fill current step inputs
            answers = await self.form_filler.fill_current_step(
                modal, job_title=job.title, job_company=job.company
            )

            # Wait briefly for navigation buttons to be interactive
            submit_btn = self.page.locator(
                'button[data-view-name="submit-unify"], button[aria-label="Submit application"], button:has-text("Submit application"), button:has-text("تقديم الاستمارة")'
            ).first
            next_btn = self.page.locator(
                'button[data-view-name="continue-unify"], button[aria-label="Continue to next step"], button:has-text("Next"), button:has-text("التالي")'
            ).first
            review_btn = self.page.locator(
                'button[data-view-name="review-unify"], button[aria-label="Review your application"]'
            ).first

            # If none are visible immediately, give up to 3s for page transition / validation
            for _ in range(6):
                if (await submit_btn.count() > 0 and await submit_btn.is_visible()) or \
                   (await next_btn.count() > 0 and await next_btn.is_visible()) or \
                   (await review_btn.count() > 0 and await review_btn.is_visible()):
                    break
                await asyncio.sleep(0.5)

            # 2. Check for Submit button
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                if dry_run:
                    logger.info("🛡️ [DRY RUN] Final Submit button reached! Validated all steps without submitting.")
                    # Dismiss modal cleanly
                    await self._dismiss_modal(modal)
                    return (True, "Dry-run successful: verified all steps up to Submit")
                else:
                    logger.info("🚀 Clicking 'Submit application'...")
                    try:
                        await submit_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
                    await submit_btn.click()
                    await asyncio.sleep(3.0)
                    # Close confirmation if present
                    close_btn = self.page.locator('button[aria-label="Dismiss"], button:has-text("Done"), button[aria-label="رفض"]').first
                    if await close_btn.count() > 0:
                        await close_btn.click()
                    return (True, "Application submitted successfully!")

            # 3. Check for Next button first (prioritize Next over Review until Next is no longer present)
            if await next_btn.count() > 0 and await next_btn.is_visible():
                logger.info("Clicking 'Next' button...")
                await next_btn.click()
                await asyncio.sleep(2.0)

                # Check if there is a validation error preventing navigation
                error_loc = modal.locator('.artdeco-inline-feedback--error, [aria-invalid="true"]')
                if await error_loc.count() > 0 and await error_loc.first.is_visible():
                    err_text = (await error_loc.first.inner_text()).strip()
                    logger.warning(f"Validation error on form: {err_text}")
                    await self._dismiss_modal(modal)
                    return (False, f"Validation error: {err_text}")
                continue

            # 4. Check for Review button (strictly review-unify, never review-edit-unify)
            if await review_btn.count() > 0 and await review_btn.is_visible():
                logger.info("Clicking 'Review' button...")
                await review_btn.click()
                await asyncio.sleep(2.5)

                # Check if there is a validation error preventing navigation
                error_loc = modal.locator('.artdeco-inline-feedback--error, [aria-invalid="true"]')
                if await error_loc.count() > 0 and await error_loc.first.is_visible():
                    err_text = (await error_loc.first.inner_text()).strip()
                    logger.warning(f"Validation error after Review: {err_text}")
                    await self._dismiss_modal(modal)
                    return (False, f"Validation error: {err_text}")
                continue

            # If none of Next, Review, Submit are visible, we might be stuck
            break

        await self._dismiss_modal(modal)
        return (False, f"Application flow ended unexpectedly at step {current_step}")

    async def _dismiss_modal(self, modal):
        """Safely closes modal without submitting."""
        try:
            dismiss_btn = self.page.locator(
                'button[data-view-name*="dismiss"], button[aria-label="Dismiss"], button[data-test-modal-close-btn]'
            ).first
            if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                await dismiss_btn.click()
                await asyncio.sleep(0.8)

                # Confirm discard prompt if modal asks "Discard application?"
                discard_btn = self.page.locator(
                    'button[data-control-name="discard_application_confirm_btn"], button[data-view-name*="discard"], button:has-text("Discard")'
                ).first
                if await discard_btn.count() > 0 and await discard_btn.is_visible():
                    await discard_btn.click()
                    await asyncio.sleep(0.5)
        except Exception as e:
            logger.debug(f"Error dismissing modal: {e}")
