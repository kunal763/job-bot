"""Intelligent label-to-input form filling engine for application modals."""

import asyncio
from pathlib import Path
from typing import Any
from playwright.async_api import ElementHandle, Locator, Page
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.models import UserProfile
from job_bot.utils.logger import logger


class FormFiller:
    """Fills out dynamic job application forms using user profile, cache, and AI Copilot."""

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

    async def fill_current_step(self, modal_locator: Locator, job_title: str = "", job_company: str = "") -> dict[str, Any]:
        """Inspects all visible inputs in the modal and fills them."""
        # 1. Fill Text and Number inputs
        await self._fill_text_inputs(modal_locator, job_title, job_company)

        # 2. Fill Textareas
        await self._fill_textareas(modal_locator, job_title, job_company)

        # 3. Fill Select / Dropdowns
        await self._fill_select_dropdowns(modal_locator, job_title, job_company)

        # 4. Fill Radio button groups
        await self._fill_radio_groups(modal_locator, job_title, job_company)

        # 5. Handle File Uploads (Resume)
        await self._handle_file_uploads(modal_locator)

        return self.answers_log

    async def _fill_text_inputs(self, modal: Locator, job_title: str, job_company: str):
        text_inputs = modal.locator('input[type="text"], input[type="number"], input[type="tel"]:not([disabled])')
        count = await text_inputs.count()

        for i in range(count):
            input_el = text_inputs.nth(i)
            if not await input_el.is_visible():
                continue

            current_val = await input_el.input_value()
            if current_val and current_val.strip():
                # Already populated (e.g. LinkedIn prefilled phone/email)
                continue

            label = await self._find_label_for_element(input_el)
            if not label:
                label = await input_el.get_attribute("aria-label") or await input_el.get_attribute("placeholder") or "Field"

            answer = self._get_answer_for_question(label, options=None, job_title=job_title, job_company=job_company)
            logger.info(f"  [Input] '{label}' -> filling '{answer}'")
            await input_el.click()
            await input_el.fill(str(answer))
            self.answers_log[label] = answer
            await asyncio.sleep(0.15)

    async def _fill_textareas(self, modal: Locator, job_title: str, job_company: str):
        textareas = modal.locator("textarea:not([disabled])")
        count = await textareas.count()

        for i in range(count):
            ta = textareas.nth(i)
            if not await ta.is_visible():
                continue

            current_val = await ta.input_value()
            if current_val and current_val.strip():
                continue

            label = await self._find_label_for_element(ta)
            if not label:
                label = await ta.get_attribute("aria-label") or "Open-ended question"

            answer = self._get_answer_for_question(label, options=None, job_title=job_title, job_company=job_company)
            logger.info(f"  [Textarea] '{label[:40]}...' -> filling answer")
            await ta.click()
            await ta.fill(str(answer))
            self.answers_log[label] = answer
            await asyncio.sleep(0.15)

    async def _fill_select_dropdowns(self, modal: Locator, job_title: str, job_company: str):
        selects = modal.locator("select:not([disabled])")
        count = await selects.count()

        for i in range(count):
            sel = selects.nth(i)
            if not await sel.is_visible():
                continue

            sel_id = (await sel.get_attribute("id") or "").lower()
            sel_name = (await sel.get_attribute("name") or "").lower()
            if any(ign in (sel_id + " " + sel_name) for ign in ["footer", "global", "locale"]):
                continue

            current_val = await sel.input_value()
            label = await self._find_label_for_element(sel) or "Dropdown"

            # Skip footer/global language selectors
            if any(ign in label.lower() for ign in ["select language", "change language", "global language", "تحديد اللغة", "language"]):
                continue

            # Get option texts
            option_locators = sel.locator("option")
            opt_count = await option_locators.count()
            options: list[str] = []
            values: list[str] = []
            for o in range(opt_count):
                opt = option_locators.nth(o)
                is_disabled = await opt.get_attribute("disabled") is not None
                if is_disabled:
                    continue
                text = (await opt.inner_text()).strip()
                val = await opt.get_attribute("value")
                if val is None:
                    val = text
                # Skip placeholder options
                if not text or not val or any(ph in text.lower() for ph in ["select an option", "choose an option", "select one", "تحديد خيار", "اختر"]):
                    continue
                options.append(text)
                values.append(val)

            if not options:
                continue

            # Skip language dropdown if it has multiple world languages
            if len(options) > 15 and any("english" in o.lower() for o in options) and any("español" in o.lower() or "deutsch" in o.lower() or "العربية" in o.lower() for o in options):
                continue

            # Smart heuristics for common dropdowns
            chosen_val = None
            lbl_lower = label.lower()

            if any(k in lbl_lower for k in ["country code", "phone code", "dialing code", "country", "هاتف", "دولة"]):
                for idx, opt_text in enumerate(options):
                    if any(ind in opt_text.lower() for ind in ["india", "+91", "الهند"]):
                        chosen_val = values[idx]
                        answer = opt_text
                        break

            if not chosen_val and any(k in lbl_lower for k in ["location", "city", "office", "site", "مكان", "مدينة"]):
                cand_loc = (self.profile.personal.location or "India").lower()
                cand_city = (getattr(self.profile.personal, "city", None) or "Pune").lower()
                for idx, opt_text in enumerate(options):
                    o_low = opt_text.lower()
                    if cand_city in o_low or "india" in o_low or "remote" in o_low:
                        chosen_val = values[idx]
                        answer = opt_text
                        break

            if not chosen_val and "language" in lbl_lower:
                for idx, opt_text in enumerate(options):
                    if "english" in opt_text.lower():
                        chosen_val = values[idx]
                        answer = opt_text
                        break

            if not chosen_val:
                answer = self._get_answer_for_question(label, options=options, job_title=job_title, job_company=job_company)
                # Find closest matching option value
                for idx, opt_text in enumerate(options):
                    if opt_text.lower() == str(answer).lower() or str(answer).lower() in opt_text.lower():
                        chosen_val = values[idx]
                        break

            if chosen_val:
                logger.info(f"  [Select] '{label}' -> selecting '{answer}'")
                try:
                    await sel.select_option(value=chosen_val, timeout=5000)
                    self.answers_log[label] = answer
                except Exception as e:
                    logger.warning(f"Error selecting option '{chosen_val}': {e}")
            elif values:
                logger.info(f"  [Select fallback] '{label}' -> selecting '{options[0]}'")
                try:
                    await sel.select_option(value=values[0], timeout=5000)
                    self.answers_log[label] = options[0]
                except Exception as e:
                    logger.warning(f"Error selecting fallback option '{values[0]}': {e}")

            await asyncio.sleep(0.15)

    async def _fill_radio_groups(self, modal: Locator, job_title: str, job_company: str):
        fieldsets = modal.locator("fieldset")
        count = await fieldsets.count()

        for f in range(count):
            fs = fieldsets.nth(f)
            if not await fs.is_visible():
                continue

            # Question is usually in <legend> or preceding <p>/heading or container
            legend = fs.locator("legend")
            if await legend.count() > 0 and (await legend.inner_text()).strip():
                question = (await legend.inner_text()).strip()
            else:
                try:
                    question = await fs.evaluate('''el => {
                        let prev = el.previousElementSibling;
                        if (prev && prev.innerText) return prev.innerText.trim();
                        let p = el.closest('div[componentkey], div')?.querySelector('p, h3, h4, span');
                        return p ? p.innerText.trim() : 'Choice Question';
                    }''')
                except Exception:
                    question = "Choice Question"

            # Check if any choice is already checked/selected
            try:
                already_checked = await fs.evaluate('''el => {
                    let checked = el.querySelector('[aria-checked="true"], input:checked');
                    return !!checked;
                }''')
                if already_checked:
                    continue
            except Exception:
                pass

            # Find clickable choice targets (supports modern role="checkbox"/"radio", label, or direct inputs)
            targets = await fs.locator('div[role="checkbox"], div[role="radio"], label, input[type="radio"]').all()
            if not targets:
                continue

            options: list[str] = []
            valid_targets = []
            for t_el in targets:
                raw_txt = (await t_el.inner_text()).strip()
                clean_txt = "".join(c for c in raw_txt if c.isalnum() or c in (" ", "-", "/", "+")).strip()
                if clean_txt and clean_txt not in options:
                    options.append(clean_txt)
                    valid_targets.append((clean_txt, t_el))

            if not valid_targets:
                continue

            answer = self._get_answer_for_question(question, options=options, job_title=job_title, job_company=job_company)

            # Click corresponding choice option
            clicked = False
            for opt_txt, opt_el in valid_targets:
                if opt_txt.lower() == str(answer).lower() or str(answer).lower() in opt_txt.lower():
                    await opt_el.click()
                    clicked = True
                    logger.info(f"  [Choice] '{question}' -> clicked '{opt_txt}'")
                    self.answers_log[question] = opt_txt
                    break

            if not clicked and valid_targets:
                await valid_targets[0][1].click()
                logger.info(f"  [Choice fallback] '{question}' -> clicked '{valid_targets[0][0]}'")
                self.answers_log[question] = valid_targets[0][0]

            await asyncio.sleep(0.15)

    async def _handle_file_uploads(self, modal: Locator):
        """Attaches candidate resume if an upload file input exists and none is chosen."""
        file_inputs = modal.locator('input[type="file"]')
        count = await file_inputs.count()
        if count == 0:
            return

        resume_path = self.profile.documents.resume_path
        if not resume_path.exists():
            logger.warning(f"Resume path does not exist: {resume_path}")
            return

        for i in range(count):
            fin = file_inputs.nth(i)
            # Check if already has a selected resume on LinkedIn
            logger.info(f"  [Upload] Attaching resume from '{resume_path}'...")
            await fin.set_input_files(str(resume_path))
            self.answers_log["Resume Upload"] = resume_path.name
            await asyncio.sleep(0.5)

    async def _find_label_for_element(self, element: Locator) -> str | None:
        """Finds label text associated with an element."""
        # 1. Check ID-based label
        elem_id = await element.get_attribute("id")
        if elem_id:
            lbl = self.page.locator(f'label[for="{elem_id}"]')
            if await lbl.count() > 0:
                text = (await lbl.first.inner_text()).strip()
                if text:
                    return text

        # 2. Check parent label
        try:
            parent_lbl = element.locator("xpath=ancestor::label[1]")
            if await parent_lbl.count() > 0:
                text = (await parent_lbl.first.inner_text()).strip()
                if text:
                    return text
        except Exception:
            pass

        # 3. Check aria-label
        aria_label = await element.get_attribute("aria-label")
        if aria_label:
            return aria_label.strip()

        return None

    def _get_answer_for_question(
        self,
        question: str,
        options: list[str] | None,
        job_title: str,
        job_company: str,
    ) -> str:
        """Check cache -> AI Copilot -> return answer."""
        if self.repository:
            cached = self.repository.get_cached_answer(question)
            if cached:
                return cached

        ans = self.copilot.answer_question(
            question=question,
            options=options,
            job_title=job_title,
            job_company=job_company,
        )

        if self.repository and ans:
            self.repository.cache_answer(question, ans, source="copilot")

        return ans
