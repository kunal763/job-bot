"""AI Copilot / LLM client for answering dynamic job application questions and generating founder pitches.

Supports Groq (free tier Llama-3, Qwen-2.5/3, GPT-OSS), Google Gemini, and intelligent
profile-based heuristics.
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

    def get_resume_context(self) -> str:
        """Retrieves raw resume text for deep candidate context."""
        for path_candidate in [
            BASE_DIR / "Kunal_resume.txt",
            Path("Kunal_resume.txt"),
            BASE_DIR / "data" / "Kunal_resume.txt",
        ]:
            if path_candidate.exists():
                try:
                    return path_candidate.read_text(encoding="utf-8").strip()
                except Exception:
                    pass

        # Fallback to pdftotext on resume_path if txt not found
        try:
            res_pdf = self.profile.documents.resume_path
            if res_pdf and res_pdf.exists():
                import subprocess
                out = subprocess.check_output(["pdftotext", str(res_pdf), "-"], timeout=5)
                text = out.decode("utf-8", errors="ignore").strip()
                if len(text) > 100:
                    return text
        except Exception:
            pass

        # Fallback to profile summary
        skills_str = ", ".join(self.profile.career.skills)
        return (
            f"Candidate: {self.profile.personal.first_name} {self.profile.personal.last_name}\n"
            f"Title: {self.profile.career.current_title}\n"
            f"Experience: {self.profile.career.total_years_experience} years\n"
            f"Skills: {skills_str}\n"
            f"Summary: {self.profile.career.summary or ''}"
        )

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 600,
        temperature: float = 0.2,
    ) -> str | None:
        """Directly invokes LLM (Groq or Gemini) and extracts clean text."""
        # 1. Groq
        if self.groq_client:
            models_to_try = [
                config.groq_model,
                "qwen/qwen3.8-27b",
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
            ]
            # preserve order while removing duplicates
            seen_models = set()
            ordered_models = []
            for m in models_to_try:
                if m not in seen_models:
                    seen_models.add(m)
                    ordered_models.append(m)

            for model_name in ordered_models:
                try:
                    response = self.groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    choice = response.choices[0]
                    content = (choice.message.content or "").strip()
                    if content:
                        return content
                except Exception as e:
                    logger.debug(f"Groq API error on model {model_name}: {e}. Trying next...")

        # 2. Gemini fallback
        if self.gemini_client:
            try:
                combined_prompt = f"{system_prompt}\n\n{user_prompt}"
                response = self.gemini_client.models.generate_content(
                    model=config.gemini_model,
                    contents=combined_prompt,
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                logger.warning(f"Gemini API error: {e}")

        return None

    def answer_question(
        self,
        question: str,
        options: list[str] | None = None,
        job_title: str | None = None,
        job_company: str | None = None,
    ) -> str:
        """Answers an application form question using deterministic rules or LLM."""
        # 1. First check deterministic profile heuristic
        heuristic = self._heuristic_answer(question, options)
        if heuristic is not None:
            return heuristic

        # 2. Call LLM (Groq or Gemini)
        user_prompt = self._build_prompt(question, options, job_title, job_company)
        system_prompt = (
            "You are an expert career assistant completing a job application on behalf of the candidate Kunal Singh. "
            "Answer concisely, truthfully based only on the candidate's profile and resume, and professionally. "
            "If the question asks for a number, return only the number. "
            "If options are provided, return exactly one of the options word-for-word. "
            "If it is a cover letter, non-tech achievement, or open-ended essay question, write a compelling, substantive response (at least 60-120 characters) highlighting the candidate's relevant achievements, competitive grit, or engineering solutions."
        )

        llm_answer = self._call_llm(system_prompt, user_prompt, max_tokens=600, temperature=0.2)
        if llm_answer:
            return self._clean_llm_answer(llm_answer, options)

        # Default fallback when no LLM response is obtained
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

        resume_context = self.get_resume_context()

        prompt = (
            f"Candidate Profile:\n{json.dumps(profile_summary, indent=2)}\n\n"
            f"Candidate Resume Details:\n{resume_context[:2500]}\n\n"
        )
        if job_title or job_company:
            prompt += f"Applying for Role: {job_title or 'Engineer'} at {job_company or 'Company'}\n\n"
        prompt += f"Application Question: {question}\n"
        if options:
            prompt += f"Available Choices (pick exact match): {', '.join(options)}\n"
        prompt += "\nProvide the single most accurate, authentic and direct answer:"
        return prompt

    def _heuristic_answer(self, question: str, options: list[str] | None) -> str | None:
        """Fast regex & keyword rule matching against profile details for standard form inputs."""
        q_clean = question.strip()
        q_lower = q_clean.lower()

        # Guard: Never apply short heuristics to open-ended / subjective / essay prompts
        if len(q_clean) > 75 or any(term in q_lower for term in [
            "accomplish", "impressive", "build", "pitch", "why do you",
            "tell us", "describe", "elaborate", "share 2", "startup", "ideas",
            "non-tech", "looking for", "mission", "project", "greatest"
        ]):
            return None

        # Check years of experience for a skill: "how many years of work experience do you have with [Skill]?"
        exp_match = re.search(r"years of (?:work )?experience (?:do you have )?(?:with|in)?\s+([a-zA-Z0-9#\+\.]+)", q_lower)
        if exp_match:
            skill = exp_match.group(1).strip()
            for s in self.profile.career.skills:
                if skill in s.lower() or s.lower() in skill:
                    return str(int(self.profile.career.total_years_experience))
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
            if k_clean in q_lower and len(q_lower) < 60:
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

        # Yes/No questions
        if any(q_lower.startswith(prefix) for prefix in ["have you", "do you", "are you", "will you", "can you", "did you", "is your"]):
            if any(neg in q_lower for neg in ["sponsorship", "visa", "felony", "crime"]):
                return "No"
            if options is None and any(tech in q_lower for tech in ["used", "experience", "worked with"]):
                return str(int(self.profile.career.total_years_experience))
            return "Yes"

        # URLs & Profiles - only when directly asking for link/URL
        if len(q_clean) < 60:
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
        cleaned = answer.strip().strip('"').strip("'")
        if options:
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
            for opt in options:
                if opt.strip().lower() in ["yes", "true", "i agree"]:
                    return opt
            return options[0]

        q = question.lower()
        if any(term in q for term in ["years", "year", "expérience", "experience", "année", "annee", "años", "anos", "jahre", "سنوات", "combien", "cuantos"]):
            return str(int(self.profile.career.total_years_experience))
        return "Yes"

    async def generate_note(
        self,
        profile: UserProfile | None = None,
        company: str = "",
        role: str = "",
        job_desc: str | None = None,
    ) -> str:
        """Generates an authentic, persuasive pitch note to startup founders citing real achievements."""
        p = profile or self.profile
        cand_name = f"{p.personal.first_name} {p.personal.last_name}".strip()
        resume_context = self.get_resume_context()

        system_prompt = (
            "You are an expert technical career advisor writing a direct, high-impact founder pitch note "
            "on behalf of Kunal Singh. Your goal is to get the startup founders to interview Kunal. "
            "Be direct, technically specific, concise, and authentic. No generic clichés, no fluff, no corporate buzzwords."
        )

        user_prompt = f"""Target Company: {company}
Target Role: {role}
{f'Company/Job Context: {job_desc[:1200]}' if job_desc else ''}

Candidate Details & Resume:
{resume_context}

Key Technical Proof Points:
- Software Developer L2 with 2+ years of production experience in high-throughput backend services and AI agent systems.
- Built an AI agent platform for website chatbots using RAG pipelines, HTTPX, Selenium, FastAPI, and vector embeddings (35,000+ pages ingested).
- C/C++ gNMI telemetry pipeline optimization at Tarana Wireless: cut payload size by 49% using YANG protobuf, and slashed execution latency from 12us to 4us (66% reduction).
- Scalable Cab Sharing Backend: 568 req/sec under 10k concurrent users, Redis caching, PostGIS geospatial matching.
- Ranked 1st in college at ICPC Asia-West Regional 2023 (14,000+ participants).

Instructions:
1. Write a sharp, punchy 3-4 sentence message directly to the founders of {company}.
2. Connect Kunal's specific technical achievements (e.g. low-latency C++, RAG/AI pipelines, high-concurrency systems, or competitive programming grit) to what {company} is building and what the {role} position needs.
3. Keep the total length strictly between 280 and 480 characters so it fits cleanly into YC founder message inboxes without being cut off.
4. Output ONLY the raw pitch message text. Do NOT include greetings with placeholders, subject lines, quotation marks, or explanations.
"""

        note = self._call_llm(system_prompt, user_prompt, max_tokens=400, temperature=0.3)

        if note and len(note) >= 60 and "not specified" not in note.lower():
            # Clean outer quotes if any
            clean_note = note.strip().strip('"').strip("'")
            return clean_note

        # Dynamic role-specific fallback if LLM is unavailable
        return self._generate_smart_fallback_note(company, role, job_desc)

    def _generate_smart_fallback_note(self, company: str, role: str, job_desc: str | None) -> str:
        """Context-aware fallback pitch tailored to company and role domain."""
        role_lower = (role or "").lower()
        desc_lower = (job_desc or "").lower()

        if any(k in role_lower or k in desc_lower for k in ["c++", "low latency", "systems", "embedded", "telemetry", "audio", "kernel"]):
            return (
                f"Hi {company} team, I am Kunal Singh. At Tarana Wireless, I optimized C++ telemetry pipelines to slash latency from 12us to 4us and cut payload by 49%, and ranked 1st in college at ICPC Asia-West. "
                f"The {role} role matches my passion for high-performance systems engineering, and I would love to build low-latency infrastructure at {company}."
            )
        elif any(k in role_lower or k in desc_lower for k in ["ai", "rag", "agent", "llm", "scraping", "nlp"]):
            return (
                f"Hi {company} team, I am Kunal Singh. I engineered an AI agent platform utilizing RAG pipelines and vector embeddings that ingested 35k+ pages across 10 deployments at scale. "
                f"Your work at {company} on {role} is exciting, and I can immediately contribute to scaling your AI pipelines and high-throughput backend services."
            )
        else:
            return (
                f"Hi {company} team, I am Kunal Singh, a backend engineer with 2+ years of experience in Python, FastAPI, C++, and distributed systems. "
                f"I have built scalable backends handling 568 req/s under 10k concurrent users and optimized production data pipelines. "
                f"I would love to bring this execution velocity to the {role} role at {company}."
            )
