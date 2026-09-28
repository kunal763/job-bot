"""Y Combinator (Work at a Startup) Search & Application Automation."""

import asyncio
import re
import urllib.parse
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from job_bot.config import config
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.engine.external_filler import ExternalFormFiller
from job_bot.engine.platforms.base import JobPlatform
from job_bot.engine.salary_parser import SalaryParser, evaluate_salary
from job_bot.models import ApplicationStatus, JobListing, UserProfile
from job_bot.utils.logger import logger


class YCombinatorPlatform(JobPlatform):
    """Handles Y Combinator startup job discovery and autonomous application on Work at a Startup."""

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
        """Search Y Combinator startup jobs and extract matching listings.

        Args:
            keywords: Target keywords (e.g. ['Python'], ['Backend'], ['AI'])
            location: Target location (e.g. 'India', 'Pune', 'Remote', 'all')
            limit: Maximum listings to return
            easy_apply_only: Unused on YC (all are direct apply)
        """
        logger.info(f"Searching Y Combinator startup jobs for: {keywords} in {location}...")

        base_search_url = "https://www.workatastartup.com/jobs/v2?role=eng"
        listings: list[JobListing] = []
        seen_job_ids: set[str] = set()

        # Build list of specific query strings to try
        queries: list[str] = []
        loc_clean = location.strip()
        is_all_loc = not loc_clean or loc_clean.lower() == "all"

        for kw in keywords:
            kw_clean = kw.strip()
            if not kw_clean:
                continue
            if not is_all_loc:
                # 1. Keyword + Location (e.g. "Python India")
                queries.append(f"{kw_clean} {loc_clean}")
                # 2. Keyword + Remote (high-paying global roles open to India)
                queries.append(f"{kw_clean} Remote")
            # 3. Keyword alone
            queries.append(kw_clean)

        if not queries:
            queries = ["Software Engineer India", "Python", "Backend"]

        logger.info(f"Navigating to YC Work at a Startup base: {base_search_url}")
        try:
            await self.page.goto(base_search_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(2.5)
        except Exception as e:
            logger.warning(f"Error loading YC jobs page {base_search_url}: {e}")
            return listings

        for query in queries:
            if len(listings) >= limit:
                break

            logger.info(f"Submitting YC search query: '{query}'")
            try:
                search_inp = self.page.locator('#jobs-v2-search, input[placeholder*="Search" i]').first
                await search_inp.wait_for(state="visible", timeout=8000)
                await search_inp.fill(query)
                await search_inp.press("Enter")
                await asyncio.sleep(2.5)
            except Exception as e:
                logger.warning(f"Could not execute search query '{query}': {e}")
                continue

            # Extract job cards matching /jobs/<id>
            try:
                card_data = await self.page.evaluate(r"""() => {
                    const links = Array.from(document.querySelectorAll('a[href^="/jobs/"]'));
                    const results = [];
                    for (const a of links) {
                        const href = a.getAttribute('href');
                        if (!href || !/^\/jobs\/\d+/.test(href)) continue;

                        // Extract company name strictly within this link card
                        let company = '';
                        const compElem = a.querySelector('p.font-semibold') || a.querySelector('div.min-w-0 p:first-child');
                        if (compElem) {
                            company = compElem.innerText.trim();
                        } else {
                            const img = a.querySelector('img[alt]');
                            if (img) {
                                company = img.getAttribute('alt').replace(/logo$/i, '').trim();
                            }
                        }

                        // Tagline
                        let tagline = '';
                        const tagElem = a.querySelector('div.min-w-0 p:nth-child(2)');
                        if (tagElem) {
                            tagline = tagElem.innerText.trim();
                        }

                        // Job Title
                        let title = '';
                        const titleElem = a.querySelector('h3');
                        if (titleElem) {
                            title = titleElem.innerText.trim();
                        }

                        // Details (Full-time, Location, Salary)
                        let details = '';
                        const detailsElem = a.querySelector('p.line-clamp-2') || a.querySelector('div.flex-col p:last-child');
                        if (detailsElem) {
                            details = detailsElem.innerText.trim();
                        }

                        if (company && title) {
                            results.push({
                                href,
                                company,
                                tagline,
                                title,
                                details,
                            });
                        }
                    }
                    return results;
                }""")
            except Exception as e:
                logger.warning(f"Error evaluating YC job cards: {e}")
                continue

            for card in card_data:
                if len(listings) >= limit:
                    break

                href = card.get("href", "")
                m_id = re.search(r"/jobs/(\d+)", href)
                if not m_id:
                    continue
                ext_id = m_id.group(1)
                job_id = f"yc_{ext_id}"

                if job_id in seen_job_ids:
                    continue
                seen_job_ids.add(job_id)

                if self.repository and self.repository.is_job_processed(job_id):
                    logger.debug(f"Skipping already recorded/applied YC job: {job_id}")
                    continue

                company = card.get("company", "").strip()
                title = card.get("title", "").strip()
                tagline = card.get("tagline", "").strip()
                details = card.get("details", "").strip()
                full_url = f"https://www.workatastartup.com{href}"

                # Parse details: e.g. "Full-time · Bengaluru, KA, IN · ₹2M - ₹4M INR"
                parts = [p.strip() for p in re.split(r"\s*[·•|]\s*", details) if p.strip()]
                card_loc = "Remote"
                salary_raw = None

                for part in parts:
                    if any(sym in part for sym in ["₹", "$", "INR", "USD", "CAD", "EUR", "GBP"]):
                        salary_raw = part
                    elif any(kw_type in part.lower() for kw_type in ["full-time", "contract", "internship", "part-time"]):
                        continue
                    else:
                        card_loc = part

                # Normalize and parse salary
                parsed_salary = SalaryParser.parse(salary_raw)

                job_listing = JobListing(
                    id=job_id,
                    platform="yc",
                    external_job_id=ext_id,
                    title=title,
                    company=company,
                    location=card_loc,
                    salary_raw=salary_raw,
                    salary_info=parsed_salary,
                    url=full_url,
                    description=f"{title} at {company}. {tagline}. Location: {card_loc}. Salary: {salary_raw or 'Not disclosed'}.",
                    easy_apply=True,
                )
                listings.append(job_listing)
                logger.info(
                    f"  ✓ Discovered [YC]: {title} at {company} | Loc: {card_loc} | Salary: {salary_raw or 'Unlisted'}"
                )

        logger.info(f"YC search complete: extracted {len(listings)} listings.")
        return listings

    async def apply_to_job(self, job: JobListing, dry_run: bool = True) -> tuple[bool, str]:
        """Automates Y Combinator Work at a Startup application with AI pitch note to founders.

        Returns:
            (success: bool, status_message: str)
        """
        self.answers_log = {}
        logger.info(f"Navigating to YC job: {job.title} at {job.company} ({job.url})")
        try:
            await self.page.goto(job.url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(2.5)
        except Exception as e:
            logger.warning(f"Could not load YC job URL {job.url}: {e}")
            return (False, f"Navigation timeout/error: {e}")

        # 1. Verify authentic company name & title from job posting header
        try:
            page_title = await self.page.title()
            if isinstance(page_title, str):
                # Pattern: "Software Engineer - Backend at Mason | Y Combinator's Work at a Startup"
                m_title = re.search(r"^(.*?)\s+at\s+(.*?)\s*\|\s*Y Combinator", page_title, re.IGNORECASE)
                if m_title:
                    clean_title = m_title.group(1).strip()
                    clean_comp = m_title.group(2).strip()
                    if clean_comp and "y combinator" not in clean_comp.lower():
                        if clean_comp != job.company:
                            logger.info(f"Corrected company name from page title: '{job.company}' -> '{clean_comp}'")
                            job.company = clean_comp
                            if self.repository:
                                self.repository.update_job_company(job.id, clean_comp)
                        job.title = clean_title
        except Exception:
            pass

        # 2. Extract full job description for rich AI note context
        try:
            body_text = await self.page.evaluate("() => document.querySelector('main, article, div.border') ? document.querySelector('main, article, div.border').innerText : document.body.innerText")
            if body_text and len(body_text) > 100:
                job.description = body_text[:4000]
        except Exception:
            pass

        # 3. Check if already applied
        applied_indicators = self.page.locator(
            'button:has-text("Applied"), '
            'div:has-text("You have applied to this role"), '
            'div:has-text("Application submitted"), '
            'span:has-text("Applied")'
        )
        if await applied_indicators.count() > 0:
            return (True, "Already applied previously on Work at a Startup.")

        # 4. Find Apply button / link (handles both logged-in and logged-out variants)
        apply_btn = self.page.locator(
            'a[class*="bg-orange"]:has-text("Apply"), '
            'a:has-text("Apply to this role"), '
            'button:has-text("Apply to this role"), '
            'a:has-text("Apply Now"), '
            'button:has-text("Apply Now"), '
            'a:has-text("Apply"), '
            'button:has-text("Apply")'
        ).first

        try:
            await apply_btn.wait_for(state="visible", timeout=6000)
        except Exception:
            pass

        if await apply_btn.count() == 0 or not await apply_btn.is_visible():
            return (False, "Apply button not found on YC job posting.")

        href = await apply_btn.get_attribute("href")

        # 5. Check if user is logged into YC
        # If unauthenticated, the href directs to account.ycombinator.com/authenticate
        is_auth_redirect = href and "account.ycombinator.com/authenticate" in href
        if is_auth_redirect:
            if not dry_run:
                msg = (
                    "Authentication required: You are not currently logged into Work at a Startup. "
                    "Please run 'uv run job-bot login --platform yc' to log into your account once, "
                    "or start Chrome via 'uv run job-bot launch-chrome'."
                )
                logger.warning(f"⚠️ {msg}")
                return (False, msg)
            else:
                logger.info(
                    "Dry-run notice: YC session cookie is not authenticated yet. "
                    "Simulating application generation and pitch note..."
                )
                pitch_note = await self.copilot.generate_note(
                    profile=self.profile,
                    company=job.company,
                    role=job.title,
                    job_desc=job.description,
                )
                logger.info(f"AI Pitch Note Generated for {job.company}:\n{pitch_note}")
                return (True, "Dry-run successful: Application note generated and ready to submit.")

        # 6. Check if button points to an external ATS (Ashby, Greenhouse, Lever, Workable)
        if href and href.startswith("http") and not any(d in href for d in ["workatastartup.com", "ycombinator.com"]):
            logger.info(f"YC job redirects to external ATS: {href}. Launching Universal Form Filler...")
            filler = ExternalFormFiller(self.page, self.profile, self.copilot, self.repository)
            await self.page.goto(href, wait_until="domcontentloaded", timeout=45000)
            return await filler.fill_and_submit(dry_run=dry_run)

        # 7. Click Apply button to open application form / modal
        logger.info("Clicking 'Apply to this role'...")
        await apply_btn.click()
        await asyncio.sleep(2.5)

        # Check if page redirected to external ATS
        current_url = self.page.url
        if not any(d in current_url for d in ["workatastartup.com", "ycombinator.com"]):
            logger.info(f"Application redirected to external ATS ({current_url}). Delegating to Universal Form Filler...")
            filler = ExternalFormFiller(self.page, self.profile, self.copilot, self.repository)
            return await filler.fill_and_submit(dry_run=dry_run)

        # Check if a new tab opened
        if len(self.page.context.pages) > 1:
            new_tab = self.page.context.pages[-1]
            logger.info(f"Application opened in new tab: {new_tab.url}")
            filler = ExternalFormFiller(new_tab, self.profile, self.copilot, self.repository)
            res = await filler.fill_and_submit(dry_run=dry_run)
            await new_tab.close()
            return res

        # 8. Locate all application textareas (founder pitch note + custom questions)
        textareas = await self.page.locator(
            'div[role="dialog"] textarea, .modal textarea, textarea'
        ).all()

        if textareas:
            logger.info(f"Found {len(textareas)} textarea field(s) in application dialog.")
            for idx, ta in enumerate(textareas):
                try:
                    if not await ta.is_visible():
                        continue
                except Exception:
                    pass

                cur_val = (await ta.input_value()).strip()
                if cur_val:
                    continue

                # Extract preceding label / question prompt
                prompt_context = ""
                try:
                    prompt_context = await ta.evaluate("""el => {
                        let p = el.parentElement;
                        for (let i = 0; i < 4; i++) {
                            if (!p) break;
                            const label = p.querySelector('p, label, h3, h4');
                            if (label && label.innerText && label.innerText.trim().length > 3) {
                                return label.innerText.trim();
                            }
                            p = p.parentElement;
                        }
                        return el.getAttribute('placeholder') || '';
                    }""")
                except Exception:
                    pass

                p_lower = prompt_context.lower()
                is_intro_note = (
                    idx == 0
                    or any(term in p_lower for term in [
                        "reach out", "start a conversation", "share something about you",
                        "what you're looking for", "pitch", "note to founders", "message"
                    ])
                ) and not any(term in p_lower for term in [
                    "non-tech", "accomplish", "$3m", "ideas", "build", "why do you", "challenge", "bug", "peers"
                ])

                if is_intro_note:
                    logger.info(f"Generating personalized founder pitch note for {job.company}...")
                    pitch_note = await self.copilot.generate_note(
                        profile=self.profile,
                        company=job.company,
                        role=job.title,
                        job_desc=job.description,
                    )
                    await ta.fill(pitch_note)
                    try:
                        await ta.dispatch_event("input")
                        await ta.dispatch_event("change")
                    except Exception:
                        pass
                    self.answers_log["Pitch to Founders"] = pitch_note
                    logger.info(f"✓ Inserted personalized pitch to {job.company} founders.")
                else:
                    # Custom question asked by company founders
                    clean_q = re.sub(r"\s*\*+\s*$", "", prompt_context).strip()
                    logger.info(f"Answering custom question #{idx} for {job.company}: '{clean_q[:70]}...'")
                    ans = self.copilot.answer_question(
                        question=clean_q,
                        job_title=job.title,
                        job_company=job.company,
                    )
                    if asyncio.iscoroutine(ans):
                        ans = await ans
                    # Ensure minimum length of 60 chars (YC requires >= 50 for custom questions)
                    if len(ans) < 55:
                        ans = (
                            f"{ans}. I bring proven execution discipline, competitive programming problem-solving rigor, "
                            f"and hands-on experience building production-grade services that align with {job.company}'s goals."
                        )
                    await ta.fill(ans)
                    try:
                        await ta.dispatch_event("input")
                        await ta.dispatch_event("change")
                    except Exception:
                        pass
                    self.answers_log[clean_q] = ans
                    logger.info(f"✓ Answered custom question #{idx}.")

        # 9. Populate additional form inputs if present (portfolio, phone, location, custom inputs)
        inputs = await self.page.locator(
            'div[role="dialog"] input:not([type="hidden"]), .modal input:not([type="hidden"]), input[name*="portfolio" i], input[name*="phone" i]'
        ).all()
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                cur = (await inp.input_value()).strip()
                if cur:
                    continue

                inp_info = await inp.evaluate("""el => {
                    let label = "";
                    let p = el.parentElement;
                    for (let i = 0; i < 3; i++) {
                        if (!p) break;
                        const l = p.querySelector('label, p, span');
                        if (l && l.innerText && l.innerText.trim().length > 2) {
                            label = l.innerText.trim();
                            break;
                        }
                        p = p.parentElement;
                    }
                    return {
                        name: el.getAttribute('name') || '',
                        type: el.getAttribute('type') || 'text',
                        placeholder: el.getAttribute('placeholder') || '',
                        label: label
                    };
                }""")
            except Exception:
                continue

            identifier = f"{inp_info.get('name', '')} {inp_info.get('placeholder', '')} {inp_info.get('label', '')}".lower()
            val = None
            if any(k in identifier for k in ["portfolio", "website", "url", "link"]):
                val = self.profile.personal.portfolio_url or "https://kunal763.github.io/"
            elif any(k in identifier for k in ["github"]):
                val = self.profile.personal.github_url or "https://github.com/kunal763"
            elif any(k in identifier for k in ["linkedin"]):
                val = self.profile.personal.linkedin_url or "https://www.linkedin.com/in/kunal-singh-chauhan"
            elif any(k in identifier for k in ["phone", "mobile", "tel"]):
                val = self.profile.personal.phone or "+917856902017"
            elif any(k in identifier for k in ["years", "experience"]):
                val = str(int(self.profile.career.total_years_experience))
            else:
                q_text = inp_info.get("label") or inp_info.get("placeholder")
                if q_text:
                    val = self.copilot.answer_question(q_text, job_title=job.title, job_company=job.company)

            if val:
                await inp.fill(val)
                try:
                    await inp.dispatch_event("input")
                    await inp.dispatch_event("change")
                except Exception:
                    pass

        # 10. Locate submit button & verify enabled state
        submit_btn = self.page.locator(
            'div[role="dialog"] button:has-text("Send"), '
            '.modal button:has-text("Send"), '
            'button:has-text("Send"), '
            'button[type="submit"]:has-text("Submit"), '
            'button:has-text("Send Application"), '
            'button:has-text("Submit Application"), '
            'button:has-text("Apply")'
        ).first

        try:
            await submit_btn.wait_for(state="attached", timeout=6000)
        except Exception:
            pass

        if await submit_btn.count() == 0 or not await submit_btn.is_visible():
            return (False, "Submit button not found on YC application form.")

        # Give React state a moment to process filled inputs
        await asyncio.sleep(1.0)
        is_ready = await submit_btn.is_enabled()
        if not is_ready:
            await asyncio.sleep(1.5)
            is_ready = await submit_btn.is_enabled()

        # 11. Dry-run safety or final submission
        if dry_run:
            logger.info(
                f"[DRY-RUN] Application prepared for {job.company} ({job.title}). "
                f"Fields filled: {len(self.answers_log)}. Ready to send: {is_ready}."
            )
            return (True, f"Dry-run successful: All {len(self.answers_log)} modal fields and pitch note populated. Ready to send: {is_ready}.")

        if not is_ready:
            logger.warning(f"Submit button is disabled for {job.company}. Re-checking required textareas...")
            # Trigger blur and input on all textareas to ensure validation passes
            for ta in textareas:
                try:
                    await ta.focus()
                    await ta.blur()
                except Exception:
                    pass
            await asyncio.sleep(2.0)
            is_ready = await submit_btn.is_enabled()
            if not is_ready:
                return (False, f"Submit button remained disabled for {job.company}. One or more required fields may need attention.")

        logger.info(f"Submitting application to {job.company} on Work at a Startup...")
        await submit_btn.click()
        await asyncio.sleep(3.5)

        # Verify confirmation
        success_msg = self.page.locator(
            'text="Application submitted", '
            'text="Successfully applied", '
            'text="Applied", '
            'text="Your application has been sent"'
        )
        if await success_msg.count() > 0:
            logger.info(f"🎉 Successfully submitted application to {job.company} on Work at a Startup!")
            return (True, f"Submitted successfully to {job.company}")

        return (True, f"Application sent to {job.company} (pending confirmation).")
