"""AI Copilot / LLM client for answering dynamic job application questions.

Supports Groq (free tier Llama-3), Google Gemini, and rule-based heuristic fallback
when API keys are not provided.
"""

import json
import os
import re
from pathlib import Path
from typing import Any
from job_bot.config import BASE_DIR, config

from job_bot.models import UserProfile
from job_bot.utils.logger import logger


class AICopilot:
    """Intelligent fallback for resolving subjective or dynamic application questions."""

    def __init__(self, profile: UserProfile):
        self.profile = profile
        self.groq_client = None
        self.gemini_client = None
        self._init_clients()

    def _init_clients(self):
        # 1. Initialize Groq if key is present
        if config.groq_api_key:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=config.groq_api_key)
                logger.info("Initialized Groq AI Copilot.")
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")

        # 2. Initialize Gemini if key is present
        if not self.groq_client and config.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=config.gemini_api_key)
                logger.info("Initialized Google Gemini AI Copilot.")
            except Exception as e:
                logger.warning(f"Could not initialize Gemini client: {e}")

    def answer_question(
        self,
        question: str,
        options: list[str] | None = None,
        job_title: str | None = None,
        job_company: str | None = None,
    ) -> str:
        """Answers an application form question using LLM or profile heuristic."""
        # 1. First check deterministic profile heuristic
        heuristic = self._heuristic_answer(question, options)
        if heuristic is not None:
            return heuristic

        # 2. If options are provided and only 1 matches common terms (Yes/No)
        # 3. Call LLM (Groq or Gemini)
        prompt = self._build_prompt(question, options, job_title, job_company)

        if self.groq_client:
            models_to_try = [config.groq_model, "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
            for model_name in dict.fromkeys(models_to_try):
                try:
                    response = self.groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert career assistant completing a job application on behalf of the candidate. "
                                    "Answer concisely, truthfully based only on the candidate's profile and resume, and professionally. "
                                    "If the question asks for a number, return only the number. "
                                    "If options are provided, return exactly one of the options word-for-word. "
                                    "If it is a cover letter or open-ended essay question, write a compelling, concise response highlighting the candidate's relevant tech achievements."
                                ),
                            },
                            {"role": "user", "content": prompt},
                        ],
                        temperature=0.2,
                        max_tokens=600,
                    )
                    answer = response.choices[0].message.content.strip()
                    return self._clean_llm_answer(answer, options)
                except Exception as e:
                    logger.warning(f"Groq API error on model {model_name}: {e}. Trying fallback...")

        if self.gemini_client:
            try:
                response = self.gemini_client.models.generate_content(
                    model=config.gemini_model,
                    contents=prompt,
                )
                answer = response.text.strip()
                return self._clean_llm_answer(answer, options)
            except Exception as e:
                logger.warning(f"Gemini API error: {e}. Falling back to default.")

        # Default fallback when no LLM is configured
        return self._default_fallback(question, options)

    def _build_prompt(
        self,
        question: str,
        options: list[str] | None,
        job_title: str | None,
        job_company: str | None,
    ) -> str:
        profile_summary = {
            "name": f"{self.profile.personal.first_name} {self.profile.personal.last_name}",
            "email": self.profile.personal.email,
            "phone": self.profile.personal.phone,
            "location": self.profile.personal.location,
            "years_of_experience": self.profile.career.total_years_experience,
            "notice_period_days": self.profile.career.notice_period_days,
            "current_ctc_lpa": self.profile.career.current_ctc_lpa,
            "expected_ctc_lpa": self.profile.career.expected_ctc_lpa,
            "skills": self.profile.career.skills,
            "degree": self.profile.education.degree,
            "university": self.profile.education.university,
            "common_answers": self.profile.common_answers,
        }

        # Try to include resume text if available
        resume_snippet = ""
        for possible_path in [Path("Kunal_resume.txt"), BASE_DIR / "Kunal_resume.txt"]:
            if possible_path.exists():
                try:
                    resume_snippet = f"\nCandidate Full Resume:\n{possible_path.read_text(encoding='utf-8')[:3000]}\n"
                    break
                except Exception:
                    pass

        prompt = f"Candidate Profile:\n{json.dumps(profile_summary, indent=2)}\n{resume_snippet}\n"
        if job_title or job_company:
            prompt += f"Applying for Role: {job_title or 'Engineer'} at {job_company or 'Company'}\n\n"
        prompt += f"Application Question: {question}\n"
        if options:
            prompt += f"Available Choices (pick exact match): {', '.join(options)}\n"
        prompt += "\nProvide the single most accurate and direct answer:"
        return prompt

    def _heuristic_answer(self, question: str, options: list[str] | None) -> str | None:
        """Fast regex & keyword rule matching against profile details."""
        q_lower = question.lower()

        # Check years of experience for a skill: "how many years of work experience do you have with [Skill]?"
        exp_match = re.search(r"years of (?:work )?experience (?:do you have )?(?:with|in)?\s+([a-zA-Z0-9#\+\.]+)", q_lower)
        if exp_match:
            skill = exp_match.group(1).strip()
            for s in self.profile.career.skills:
                if skill in s.lower() or s.lower() in skill:
                    return str(int(self.profile.career.total_years_experience))
            # If not found in skills, return 1 or 2 if general, else 0
            if any(term in skill for term in ["software", "engineering", "development", "coding", "it"]):
                return str(int(self.profile.career.total_years_experience))

        # Check total years of experience or multilingual experience questions
        if any(term in q_lower for term in ["combien", "cuantos", "wie viele", "jahre", "années", "annees", "años", "anos", "سنوات"]) or \
           ("total" in q_lower and "experience" in q_lower):
            return str(int(self.profile.career.total_years_experience))

        # Notice period
        if "notice period" in q_lower:
            days = self.profile.career.notice_period_days
            if options:
                # Match exact days string (e.g. "30")
                for opt in options:
                    if str(days) in opt:
                        return opt
                if days == 30:
                    for opt in options:
                        if "1 month" in opt.lower() or "one month" in opt.lower():
                            return opt
                if days <= 15:
                    for opt in options:
                        if "immediate" in opt.lower():
                            return opt
                return options[0]
            return str(days)

        # Expected CTC
        if "expected" in q_lower and ("ctc" in q_lower or "salary" in q_lower or "compensation" in q_lower):
            return str(int(self.profile.career.expected_ctc_lpa))

        # Current CTC
        if "current" in q_lower and ("ctc" in q_lower or "salary" in q_lower or "compensation" in q_lower):
            return str(int(self.profile.career.current_ctc_lpa or 12))

        # Common answers check
        for key, val in self.profile.common_answers.items():
            k_clean = key.replace("_", " ")
            if k_clean in q_lower:
                if options:
                    for opt in options:
                        if val.lower() == opt.lower() or opt.lower().startswith(val.lower()):
                            return opt
                return val

        # Sponsorship
        if "sponsorship" in q_lower or "visa" in q_lower:
            ans = self.profile.common_answers.get("sponsorship", "No")
            if options:
                for opt in options:
                    if ans.lower() in opt.lower():
                        return opt
            return ans

        # Contact & Personal details
        if "first name" in q_lower or "given name" in q_lower:
            return self.profile.personal.first_name
        if "last name" in q_lower or "surname" in q_lower or "family name" in q_lower:
            return self.profile.personal.last_name
        if "email" in q_lower:
            return self.profile.personal.email
        if "phone" in q_lower or "mobile" in q_lower:
            return self.profile.personal.phone
        # Yes/No questions (e.g., "Have you used GitHub Copilot?", "Do you have experience with...")
        if any(q_lower.startswith(prefix) for prefix in ["have you", "do you", "are you", "will you", "can you", "did you", "is your"]):
            if any(neg in q_lower for neg in ["sponsorship", "visa", "felony", "crime"]):
                return "No"
            # If options is None (text input) and asks about using a skill/tool, recruiters expect numeric YOE
            if options is None and any(tech in q_lower for tech in ["used", "experience", "worked with"]):
                return str(int(self.profile.career.total_years_experience))
            return "Yes"


        # URLs & Profiles
        is_url_field = any(term in q_lower for term in ["profile", "url", "link", "handle", "account", "website", "portfolio"]) or q_lower in ["linkedin", "github", "website", "portfolio"]
        if is_url_field:
            if "linkedin" in q_lower and self.profile.personal.linkedin_url:
                return self.profile.personal.linkedin_url
            if "github" in q_lower and self.profile.personal.github_url:
                return self.profile.personal.github_url
            if ("website" in q_lower or "portfolio" in q_lower) and self.profile.personal.portfolio_url:
                return self.profile.personal.portfolio_url


        # Location & Address
        if "city" in q_lower:
            return "Pune"
        if "state" in q_lower or "province" in q_lower:
            return "Maharashtra"
        if "postal" in q_lower or "zip" in q_lower or "pin code" in q_lower:
            return "411015"
        if "address" in q_lower or "street" in q_lower:
            return "Pune, Maharashtra, India"
        if "country" in q_lower:
            return "India"

        # Education
        if "university" in q_lower or "college" in q_lower or "school" in q_lower:
            return self.profile.education.university
        if "degree" in q_lower:
            return self.profile.education.degree
        if "gpa" in q_lower or "percentage" in q_lower:
            return str(self.profile.education.gpa or "8.5")

        return None

    def _clean_llm_answer(self, answer: str, options: list[str] | None) -> str:
        # Strip quotes
        cleaned = answer.strip().strip('"').strip("'")
        if options:
            # find best match in options
            for opt in options:
                if opt.lower() == cleaned.lower():
                    return opt
            for opt in options:
                if opt.lower() in cleaned.lower() or cleaned.lower() in opt.lower():
                    return opt
            return options[0]
        return cleaned

    def _default_fallback(self, question: str, options: list[str] | None) -> str:
        if options:
            # Prefer 'Yes' or first option
            for opt in options:
                if opt.strip().lower() in ["yes", "true", "i agree"]:
                    return opt
            return options[0]

        q = question.lower()
        if any(term in q for term in ["years", "year", "expérience", "experience", "année", "annee", "años", "anos", "jahre", "سنوات", "combien", "cuantos"]):
            return str(int(self.profile.career.total_years_experience))
        return "Yes"

