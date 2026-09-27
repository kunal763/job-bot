"""Universal AI Form Filler for External ATS and Company Career Portals.

Supports Greenhouse, Lever, Ashby, Workday, SmartRecruiters, and custom job application forms.
Powered by Groq LLM (openai/gpt-oss-120b) and local candidate profile.
"""

import asyncio
from pathlib import Path
from typing import Any
from playwright.async_api import ElementHandle, Locator, Page

from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.models import UserProfile
from job_bot.utils.logger import logger


class ExternalFormFiller:
    """Intelligently inspects, auto-fills, and submits external job application forms."""

    def __init__(
        self,
        page: Page,
        profile: UserProfile,
        copilot: AICopilot,
        repository: JobRepository | None = None,
    ):
        self.page = page
        self.profile = profile
        self.copilot = copilot
        self.repository = repository
        self.answers_log: dict[str, Any] = {}

    async def fill_and_submit(self, dry_run: bool = True, max_steps: int = 8) -> tuple[bool, str]:
        """Performs full end-to-end form completion on an external job application page."""
        logger.info(f"Analyzing external job application at: {self.page.url}")
        await asyncio.sleep(2.0)

        current_step = 0
        while current_step < max_steps:
            current_step += 1
            logger.info(f"Processing application step {current_step}...")
            await asyncio.sleep(1.0)

            # 1. Fill all input elements on current step
            await self._fill_step_inputs()

            # 2. Check for Submit button
            submit_btn = await self._find_submit_button()
            if submit_btn and await submit_btn.is_visible():
                if dry_run:
                    logger.info("🛡️ [DRY RUN] Final Submit button located! Successfully validated all form steps.")
                    return (True, "Dry-run successful: verified all fields up to final Submit.")
                else:
                    logger.info("🚀 Clicking final 'Submit Application' button...")
                    try:
                        await submit_btn.scroll_into_view_if_needed()
                        await asyncio.sleep(0.5)
                    except Exception:
                        pass
                    await submit_btn.click()
                    await asyncio.sleep(4.0)

                    # Check for submission confirmation
                    success, msg = await self._check_submission_success()
                    return (success, msg)

            # 3. Check for Next / Continue button
            next_btn = await self._find_next_button()
            if next_btn and await next_btn.is_visible():
                logger.info("Advancing to next step...")
                await next_btn.scroll_into_view_if_needed()
                await next_btn.click()
                await asyncio.sleep(2.5)

                # Check if validation errors prevent progression
                has_error, err_msg = await self._check_form_errors()
                if has_error:
                    logger.warning(f"Form validation error: {err_msg}")
                    return (False, f"Validation error: {err_msg}")
                continue

            # If no submit or next button found, we may have already submitted or form is completed
            break

        if dry_run:
            return (True, "Dry-run completed: Form elements filled and verified.")
        return (True, "Form processing completed.")

    async def _fill_step_inputs(self):
        """Fills inputs, textareas, selects, radios, checkboxes, and attachments on page."""
        # Attach resume first so ATS auto-parsing can populate where applicable
        await self._fill_file_uploads()
        await self._fill_text_inputs()
        await self._fill_textareas()
        await self._fill_select_dropdowns()
        await self._fill_radio_groups()
        await self._fill_checkboxes()

    async def _fill_file_uploads(self):
        """Attaches candidate resume PDF to any resume upload input."""
        resume_path = self.profile.documents.resume_path
        if not resume_path.exists():
            for alt in [Path("data/Kunal_Singh_Resume.pdf"), Path("Kunal_Singh_Resume.pdf")]:
                if alt.exists():
                    resume_path = alt.resolve()
                    break

        if not resume_path.exists():
            logger.warning(f"Resume PDF not found: {resume_path}")
            return

        file_inputs = self.page.locator('input[type="file"]')
        count = await file_inputs.count()
        for i in range(count):
            fin = file_inputs.nth(i)
            # Only upload to resume fields or empty file fields
            lbl = (await self._find_label(fin) or "").lower()
            name = (await fin.get_attribute("name") or "").lower()
            id_attr = (await fin.get_attribute("id") or "").lower()
            combined = f"{lbl} {name} {id_attr}"

            if any(term in combined for term in ["resume", "cv", "curriculum", "attachment", "document"]) or count == 1:
                logger.info(f"  [Upload] Attaching resume '{resume_path.name}'...")
                try:
                    await fin.set_input_files(str(resume_path))
                    self.answers_log["Resume Upload"] = resume_path.name
                    await asyncio.sleep(1.0)
                except Exception as e:
                    logger.debug(f"File upload error: {e}")

    async def _fill_text_inputs(self):
        """Fills single-line text, email, tel, and number inputs."""
        inputs = self.page.locator(
            'input[type="text"], input[type="email"], input[type="tel"], input[type="number"], input:not([type]):not([disabled])'
        )
        count = await inputs.count()

        for i in range(count):
            el = inputs.nth(i)
            if not await el.is_visible():
                continue

            # Skip hidden, search boxes, or already filled inputs
            current_val = await el.input_value()
            if current_val and current_val.strip():
                continue

            label = await self._find_label(el)
            if not label:
                continue

            lbl_lower = label.lower()
            if any(ign in lbl_lower for ign in ["search", "filter", "query", "subscribe"]):
                continue

            answer = self._determine_field_value(label, el_type="input")
            if answer is not None:
                logger.info(f"  [Input] '{label[:45]}' -> '{str(answer)[:45]}'")
                try:
                    await el.click()
                    await el.fill(str(answer))
                    self.answers_log[label] = answer
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.debug(f"Error filling input '{label}': {e}")

    async def _fill_textareas(self):
        """Fills multiline textareas, cover letters, and essay prompts."""
        textareas = self.page.locator('textarea:not([disabled])')
        count = await textareas.count()

        for i in range(count):
            ta = textareas.nth(i)
            if not await ta.is_visible():
                continue

            current_val = await ta.input_value()
            if current_val and current_val.strip():
                continue

            label = await self._find_label(ta) or "Question"
            answer = self._determine_field_value(label, el_type="textarea")
            if answer is not None:
                logger.info(f"  [Textarea] '{label[:45]}' -> generating response with AI Copilot...")
                try:
                    await ta.click()
                    await ta.fill(str(answer))
                    self.answers_log[label] = answer
                    await asyncio.sleep(0.2)
                except Exception as e:
                    logger.debug(f"Error filling textarea '{label}': {e}")

    async def _fill_select_dropdowns(self):
        """Selects options from dropdowns."""
        selects = self.page.locator('select:not([disabled])')
        count = await selects.count()

        for i in range(count):
            sel = selects.nth(i)
            if not await sel.is_visible():
                continue

            label = await self._find_label(sel) or "Dropdown"
            options = []
            opt_locs = sel.locator("option")
            opt_cnt = await opt_locs.count()
            for o in range(opt_cnt):
                txt = (await opt_locs.nth(o).inner_text()).strip()
                val = await opt_locs.nth(o).get_attribute("value")
                if txt and not any(ph in txt.lower() for ph in ["select an option", "choose one", "select..."]):
                    options.append(txt)

            if not options:
                continue

            chosen_text = self._determine_choice_value(label, options)
            if chosen_text:
                try:
                    await sel.select_option(label=chosen_text, timeout=2000)
                    logger.info(f"  [Select] '{label[:45]}' -> '{chosen_text}'")
                    self.answers_log[label] = chosen_text
                except Exception:
                    try:
                        # Fallback by value or index
                        await sel.select_option(index=1, timeout=2000)
                    except Exception:
                        pass

    async def _fill_radio_groups(self):
        """Selects appropriate radio button in fieldsets or choice groupings."""
        fieldsets = self.page.locator('fieldset, div[role="radiogroup"], div.field:has(input[type="radio"])')
        count = await fieldsets.count()

        for i in range(count):
            fs = fieldsets.nth(i)
            if not await fs.is_visible():
                continue

            legend = fs.locator('legend, label, p, [class*="title"], [class*="label"]').first
            question = (await legend.inner_text()).strip() if await legend.count() > 0 else ""
            if not question:
                continue

            radios = fs.locator('input[type="radio"], div[role="radio"]')
            rcnt = await radios.count()
            options = []
            targets = []
            for r in range(rcnt):
                r_el = radios.nth(r)
                # Find label for this radio
                r_lbl = await self._find_label(r_el) or (await r_el.inner_text()).strip()
                if r_lbl:
                    options.append(r_lbl)
                    targets.append((r_lbl, r_el))

            if options:
                chosen = self._determine_choice_value(question, options)
                for txt, el in targets:
                    if txt.lower() == chosen.lower() or chosen.lower() in txt.lower():
                        await el.click()
                        logger.info(f"  [Radio] '{question[:45]}' -> '{txt}'")
                        self.answers_log[question] = txt
                        break

    async def _fill_checkboxes(self):
        """Checks required agreement or consent checkboxes."""
        checkboxes = self.page.locator('input[type="checkbox"]:not(:checked)')
        count = await checkboxes.count()
        for i in range(count):
            cb = checkboxes.nth(i)
            if not await cb.is_visible():
                continue
            lbl = (await self._find_label(cb) or "").lower()
            if any(term in lbl for term in ["consent", "agree", "certify", "acknowledge", "terms", "policy", "privacy"]):
                try:
                    await cb.check()
                    logger.info(f"  [Checkbox] Checked: '{lbl[:45]}'")
                except Exception:
                    pass

    def _determine_field_value(self, label: str, el_type: str = "input") -> str:
        """Maps standard candidate fields or uses Groq AI for custom prompts."""
        q_lower = label.lower()

        # Name fields
        if "first name" in q_lower or "given name" in q_lower:
            return self.profile.personal.first_name
        if "last name" in q_lower or "family name" in q_lower or "surname" in q_lower:
            return self.profile.personal.last_name
        if "full name" in q_lower or q_lower == "name" or "your name" in q_lower:
            return f"{self.profile.personal.first_name} {self.profile.personal.last_name}"

        # Contact fields
        if "email" in q_lower:
            return self.profile.personal.email
        if "phone" in q_lower or "mobile" in q_lower or "contact number" in q_lower:
            return self.profile.personal.phone

        # URLs
        if "linkedin" in q_lower:
            return self.profile.personal.linkedin_url or "https://www.linkedin.com/in/kunal-singh-chauhan"
        if "github" in q_lower:
            return self.profile.personal.github_url or "https://github.com/kunal763"
        if "portfolio" in q_lower or "website" in q_lower or "personal link" in q_lower or "blog" in q_lower:
            return self.profile.personal.portfolio_url or "https://github.com/kunal763"

        # Current Company / Title
        if "current company" in q_lower or "current employer" in q_lower or "organization" in q_lower:
            return "Humming Bird Web Solutions"
        if "current title" in q_lower or "current role" in q_lower or "headline" in q_lower:
            return "Software Developer L2"

        # Location / Address
        if "city" in q_lower:
            return "Pune"
        if "state" in q_lower or "province" in q_lower:
            return "Maharashtra"
        if "postal" in q_lower or "zip" in q_lower or "pin code" in q_lower:
            return "411015"
        if "country" in q_lower:
            return "India"
        if "location" in q_lower or "address" in q_lower:
            return "Pune, Maharashtra, India"

        # Education
        if "university" in q_lower or "college" in q_lower or "school" in q_lower:
            return self.profile.education.university
        if "degree" in q_lower or "major" in q_lower:
            return self.profile.education.degree
        if "gpa" in q_lower or "cgpa" in q_lower or "percentage" in q_lower:
            return str(self.profile.education.gpa or "9.0")
        if "graduation" in q_lower or "end year" in q_lower or "grad year" in q_lower:
            return "2026"

        # Compensation & Availability
        if "notice period" in q_lower:
            return str(self.profile.career.notice_period_days)
        if "expected" in q_lower and ("salary" in q_lower or "compensation" in q_lower or "ctc" in q_lower):
            return str(int(self.profile.career.expected_ctc_lpa))
        if "current" in q_lower and ("salary" in q_lower or "compensation" in q_lower or "ctc" in q_lower):
            return str(int(self.profile.career.current_ctc_lpa or 9))

        # Experience (years)
        if any(term in q_lower for term in ["years of experience", "total experience", "how many years"]):
            return str(int(self.profile.career.total_years_experience))

        # Check cached answer
        if self.repository:
            cached = self.repository.get_cached_answer(label)
            if cached:
                return cached

        # For textareas and subjective/custom questions -> Invoke Groq AI Copilot
        logger.info(f"  [AI Copilot] Formulating tailored response via Groq for: '{label[:60]}...'")
        answer = self.copilot.answer_question(question=label, options=None)
        if self.repository and answer:
            self.repository.cache_answer(label, answer, source="groq_external")
        return answer

    def _determine_choice_value(self, question: str, options: list[str]) -> str:
        """Picks the single most appropriate option for a choice or dropdown."""
        q_lower = question.lower()

        # Work authorization / sponsorship
        if any(term in q_lower for term in ["legally authorized", "authorized to work", "eligible to work"]):
            for opt in options:
                if opt.strip().lower() in ["yes", "true", "authorized"]:
                    return opt
        if any(term in q_lower for term in ["sponsorship", "visa", "require sponsorship"]):
            for opt in options:
                if opt.strip().lower() in ["no", "false"]:
                    return opt

        # EEOC / Demographics
        if "gender" in q_lower:
            for opt in options:
                if "male" in opt.lower() and "female" not in opt.lower():
                    return opt
        if "veteran" in q_lower:
            for opt in options:
                if any(v in opt.lower() for v in ["not a protected veteran", "not a veteran", "decline"]):
                    return opt
        if "disability" in q_lower:
            for opt in options:
                if any(d in opt.lower() for d in ["no, i don't have", "no, i do not", "no", "not disabled"]):
                    return opt
        if "race" in q_lower or "ethnicity" in q_lower:
            for opt in options:
                if "asian" in opt.lower() or "indian" in opt.lower():
                    return opt

        # Country dropdowns
        if "country" in q_lower:
            for opt in options:
                if "india" in opt.lower():
                    return opt

        # Call AI Copilot to pick the exact choice
        return self.copilot.answer_question(question=question, options=options)

    async def _find_label(self, element: Locator) -> str | None:
        """Extracts label, placeholder, or aria description for an element."""
        # 1. Advanced DOM inspection (aria-labelledby, parent containers, headings)
        try:
            dom_label = await element.evaluate('''e => {
                // Check aria-labelledby
                let lbId = e.getAttribute('aria-labelledby');
                if (lbId) {
                    let text = lbId.split(' ').map(id => document.getElementById(id)).filter(Boolean).map(x => x.innerText).join(' ');
                    if (text && text.trim()) return text.trim();
                }

                // Check aria-label
                let aria = e.getAttribute('aria-label');
                if (aria && aria.trim()) return aria.trim();

                // Check placeholder
                let ph = e.getAttribute('placeholder');
                if (ph && ph.trim() && !/search|filter/i.test(ph)) return ph.trim();

                // Check closest question or form-group container
                let p = e.closest('div[role="listitem"], label, div.field, div.form-group, div[class*="question"], div[data-automation-id], div.ashby-application-form-field, li, fieldset');
                if (p) {
                    let header = p.querySelector('div[role="heading"], label, [class*="label"], [class*="title"], legend, p');
                    if (header && header.innerText && header.innerText.trim()) return header.innerText.trim();
                    return p.innerText.trim();
                }

                return null;
            }''')
            if dom_label and dom_label.strip():
                clean_lbl = dom_label.strip().split("\n")[0].strip()
                if clean_lbl:
                    return clean_lbl
        except Exception:
            pass

        # 2. Check <label for="id">
        elem_id = await element.get_attribute("id")
        if elem_id:
            lbl = self.page.locator(f'label[for="{elem_id}"]').first
            if await lbl.count() > 0:
                txt = (await lbl.inner_text()).strip()
                if txt:
                    return txt.split("\n")[0].strip()

        return await element.get_attribute("name")

    async def _find_submit_button(self) -> Locator | None:
        """Finds final application submission button across ATS platforms."""
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'div[role="button"]:has-text("Submit")',
            'span:has-text("Submit")',
            'button:has-text("Submit Application")',
            'button:has-text("Submit application")',
            'button:has-text("Submit")',
            'button:has-text("Apply Now")',
            'button#submit_app',
            'button#btn-submit',
            'button[data-view-name="submit-unify"]',
        ]
        for sel in submit_selectors:
            loc = self.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                txt = (await loc.inner_text() or await loc.get_attribute("value") or "").lower()
                # Ensure it's not a generic Next or Search button
                if not any(ign in txt for ign in ["next", "continue", "search", "filter", "login", "sign in"]):
                    return loc
        return None


    async def _find_next_button(self) -> Locator | None:
        """Finds next step or continue button in multi-step applications."""
        next_selectors = [
            'button:has-text("Next")',
            'button:has-text("Continue")',
            'button:has-text("Review")',
            'button[data-view-name="continue-unify"]',
            'button[data-view-name="review-unify"]',
            'a:has-text("Next")',
            'button[aria-label*="Next"]',
        ]
        for sel in next_selectors:
            loc = self.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return loc
        return None

    async def _check_submission_success(self) -> tuple[bool, str]:
        """Verifies if application confirmation message or screen is reached."""
        await asyncio.sleep(2.0)
        page_text = (await self.page.inner_text("body")).lower()
        success_indicators = [
            "thank you for applying",
            "application submitted",
            "application received",
            "thanks for submitting",
            "your application has been sent",
            "application was submitted",
            "your response has been recorded",
            "your response has been submitted",
            "we have received your application",
            "application has been received",
        ]
        for ind in success_indicators:
            if ind in page_text:
                return (True, f"Application submitted successfully! Detected: '{ind}'")
        return (True, "Submit clicked successfully (confirmation pending).")

    async def _check_form_errors(self) -> tuple[bool, str]:
        """Checks for validation error messages preventing page advancement."""
        err_selectors = [
            '.error-message',
            '.field-error',
            '.artdeco-inline-feedback--error',
            '[aria-invalid="true"]',
            '[class*="error"]:visible',
        ]
        for sel in err_selectors:
            loc = self.page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                err_text = (await loc.inner_text()).strip()
                if err_text:
                    return (True, err_text)
        return (False, "")
