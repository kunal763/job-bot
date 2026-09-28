"""Telegram Bot controller for Job Bot.

Enables full remote control from your phone anywhere in the world:
- View ranked high-probability job matches
- Trigger live applications with AI pitches & custom answers
- Receive instant notifications when applications are submitted
"""

import asyncio
from typing import Any
import httpx
from job_bot.config import config
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.engine.browser import BrowserManager
from job_bot.engine.matcher import JobMatcher
from job_bot.engine.platforms.ycombinator import YCombinatorPlatform
from job_bot.models import ApplicationStatus, JobListing
from job_bot.utils.logger import logger
from job_bot.vault.profile_vault import ProfileVault


class TelegramJobBot:
    """Async Telegram Bot client with inline button support and security check."""

    def __init__(self, token: str | None = None, allowed_chat_id: str | None = None):
        self.token = token or config.telegram_bot_token
        self.allowed_chat_id = str(allowed_chat_id or config.telegram_chat_id or "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.repo = JobRepository()
        self.vault = ProfileVault()
        self.profile = self.vault.profile
        self.copilot = AICopilot(self.profile)
        self.matcher = JobMatcher(self.profile)
        self._is_applying = False

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: dict[str, Any] | None = None,
    ) -> bool:
        """Sends a message via Telegram Bot API."""
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp.status_code != 200:
                    # Retry without parse_mode if Markdown parsing failed
                    payload.pop("parse_mode", None)
                    await client.post(f"{self.base_url}/sendMessage", json=payload)
                return True
        except Exception as e:
            logger.warning(f"Error sending Telegram message: {e}")
            return False

    async def answer_callback_query(self, callback_query_id: str, text: str = ""):
        """Acknowledges inline button clicks."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id, "text": text},
                )
        except Exception:
            pass

    def _is_authorized(self, chat_id: int | str) -> bool:
        if not self.allowed_chat_id:
            # If no chat ID restricted yet, auto-accept and log
            return True
        return str(chat_id).strip() == self.allowed_chat_id

    def _get_main_keyboard(self) -> dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "🏆 Top 5 Matches", "callback_data": "rank_5"},
                    {"text": "📊 Status & Stats", "callback_data": "status"},
                ],
                [
                    {"text": "🧪 Dry-Run Top 5", "callback_data": "apply_dry"},
                    {"text": "🚀 Apply Top 5 Live", "callback_data": "apply_live"},
                ],
            ]
        }

    async def handle_start(self, chat_id: int | str):
        msg = (
            "🤖 *Job Bot Mobile Control Active*\n\n"
            "Welcome Kunal! You can control your autonomous job application agent directly from your phone.\n\n"
            "• Tap *Top 5 Matches* to view highest-probability YC roles.\n"
            "• Tap *Apply Top 5 Live* to submit within your weekly quota.\n"
            "• Tap *Status* to see applied vs queued stats."
        )
        await self.send_message(chat_id, msg, reply_markup=self._get_main_keyboard())

    async def handle_status(self, chat_id: int | str):
        applied = self.repo.get_applications(ApplicationStatus.APPLIED)
        queued = self.repo.get_applications(ApplicationStatus.QUEUED)
        yc_queued = [a for a in queued if a.get("platform") == "yc"]

        msg = (
            "📊 *Job Bot Status Report*\n\n"
            f"• *Total Applied:* `{len(applied)}` jobs\n"
            f"• *Total Queued:* `{len(queued)}` jobs\n"
            f"• *Queued YC Startups:* `{len(yc_queued)}` jobs\n"
            f"• *Candidate:* Kunal Singh (Software Developer L2)\n"
            f"• *Target Salary Threshold:* ≥ 13 LPA\n"
        )
        await self.send_message(chat_id, msg, reply_markup=self._get_main_keyboard())

    async def handle_rank(self, chat_id: int | str, limit: int = 5):
        queued = self.repo.get_applications(ApplicationStatus.QUEUED)
        yc_queued = [a for a in queued if a.get("platform") == "yc"]
        ranked = self.matcher.rank_jobs(yc_queued, limit=limit)

        if not ranked:
            await self.send_message(chat_id, "⚠️ No queued YC jobs found matching your criteria.")
            return

        lines = [f"🏆 *Top {len(ranked)} High-Probability YC Roles:*\n"]
        for idx, (job, score) in enumerate(ranked, 1):
            sal = job.get("salary_raw") or "Unlisted"
            loc = job.get("location") or "India/Remote"
            reasons = ", ".join(score.reasons[:2])
            lines.append(
                f"*{idx}. {job['title']}*\n"
                f"   🏢 *Company:* {job['company']}\n"
                f"   🔥 *Match Score:* `{score.total_score}/100`\n"
                f"   💰 *Salary:* `{sal}`\n"
                f"   📍 *Loc:* `{loc}`\n"
                f"   💡 *Fit:* {reasons}\n"
            )

        msg = "\n".join(lines)
        markup = {
            "inline_keyboard": [
                [{"text": f"🚀 Apply to These {len(ranked)} Live", "callback_data": "apply_live"}],
                [{"text": "🧪 Dry-Run First", "callback_data": "apply_dry"}],
                [{"text": "🔄 Refresh", "callback_data": "rank_5"}],
            ]
        }
        await self.send_message(chat_id, msg, reply_markup=markup)

    async def handle_apply(self, chat_id: int | str, dry_run: bool = False, limit: int = 5):
        if self._is_applying:
            await self.send_message(chat_id, "⚠️ An application batch is already in progress. Please wait.")
            return

        self._is_applying = True
        mode_label = "[DRY-RUN]" if dry_run else "[LIVE]"
        await self.send_message(chat_id, f"⚡ Starting {mode_label} applications for Top {limit} YC startups...")

        try:
            queued = self.repo.get_applications(ApplicationStatus.QUEUED)
            yc_queued = [a for a in queued if a.get("platform") == "yc"]
            ranked = self.matcher.rank_jobs(yc_queued, limit=limit)

            if not ranked:
                await self.send_message(chat_id, "No qualified jobs ready to apply.")
                self._is_applying = False
                return

            mgr = BrowserManager(headless=True)
            async with mgr:
                page = await mgr.get_page()
                platform = YCombinatorPlatform(page, self.profile, self.copilot, self.repo)

                for idx, (job_dict, score) in enumerate(ranked, 1):
                    job = JobListing(
                        id=job_dict["id"],
                        platform="yc",
                        external_job_id=job_dict["external_job_id"],
                        title=job_dict["title"],
                        company=job_dict["company"],
                        location=job_dict.get("location"),
                        salary_raw=job_dict.get("salary_raw"),
                        url=job_dict["url"],
                        easy_apply=True,
                    )

                    await self.send_message(
                        chat_id,
                        f"Targeting ({idx}/{len(ranked)}):\n*{job.title}* at *{job.company}* (Score: {score.total_score}/100)..."
                    )

                    success, msg = await platform.apply_to_job(job, dry_run=dry_run)
                    new_status = ApplicationStatus.APPLIED if (success and not dry_run) else (
                        ApplicationStatus.QUEUED if dry_run else ApplicationStatus.FAILED
                    )
                    self.repo.update_application_status(
                        job_id=job.id,
                        status=new_status,
                        notes=f"{'[DRY RUN] ' if dry_run else ''}{msg}",
                        error_message=None if success else msg,
                        custom_answers=platform.answers_log,
                    )

                    badge = "✅ SUCCESS" if success else "❌ FAILED"
                    await self.send_message(chat_id, f"{badge}: {job.company}\nStatus: _{msg}_")
                    await asyncio.sleep(2.0)

            await self.send_message(
                chat_id,
                f"🎉 {mode_label} batch complete! Processed {len(ranked)} jobs.",
                reply_markup=self._get_main_keyboard(),
            )
        except Exception as e:
            logger.error(f"Error in Telegram apply batch: {e}")
            await self.send_message(chat_id, f"❌ Error occurred during application batch: {e}")
        finally:
            self._is_applying = False

    async def run_polling(self):
        """Long-polling update loop."""
        if not self.token:
            raise ValueError(
                "TELEGRAM_BOT_TOKEN is not set. Please set it in your .env or profile."
            )

        logger.info("🤖 Starting Job Bot Telegram listener...")
        offset = 0

        async with httpx.AsyncClient(timeout=35.0) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": offset, "timeout": 25},
                    )
                    if resp.status_code != 200:
                        await asyncio.sleep(3.0)
                        continue

                    data = resp.json()
                    updates = data.get("result", [])

                    for u in updates:
                        offset = max(offset, u["update_id"] + 1)

                        # Handle messages
                        if "message" in u:
                            msg = u["message"]
                            chat_id = msg["chat"]["id"]
                            text = (msg.get("text") or "").strip()

                            if not self._is_authorized(chat_id):
                                logger.warning(f"Unauthorized Telegram access attempt from chat_id: {chat_id}")
                                continue

                            if text.startswith("/start") or text.startswith("/help"):
                                await self.handle_start(chat_id)
                            elif text.startswith("/rank"):
                                await self.handle_rank(chat_id, limit=5)
                            elif text.startswith("/apply"):
                                await self.handle_apply(chat_id, dry_run=False, limit=5)
                            elif text.startswith("/dryrun"):
                                await self.handle_apply(chat_id, dry_run=True, limit=5)
                            elif text.startswith("/status"):
                                await self.handle_status(chat_id)
                            else:
                                await self.handle_start(chat_id)

                        # Handle inline button callbacks
                        elif "callback_query" in u:
                            cb = u["callback_query"]
                            cb_id = cb["id"]
                            chat_id = cb["message"]["chat"]["id"]
                            data_cmd = cb.get("data", "")

                            if not self._is_authorized(chat_id):
                                continue

                            await self.answer_callback_query(cb_id, "Processing...")

                            if data_cmd == "rank_5":
                                await self.handle_rank(chat_id, limit=5)
                            elif data_cmd == "apply_live":
                                await self.handle_apply(chat_id, dry_run=False, limit=5)
                            elif data_cmd == "apply_dry":
                                await self.handle_apply(chat_id, dry_run=True, limit=5)
                            elif data_cmd == "status":
                                await self.handle_status(chat_id)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"Telegram polling loop exception: {e}")
                    await asyncio.sleep(2.5)
