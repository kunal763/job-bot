"""Intelligent Job Matching & Ranking Engine.

Calculates high-probability selection scores (0-100) based on:
1. Tech Stack Overlap (Python, FastAPI, C++, RAG, Distributed Systems)
2. Seniority & Experience Calibration (1-3 YOE vs Staff/Principal)
3. Location Compatibility (Pune, Bangalore, India, Remote vs US-only onsite)
4. Role Function Alignment (Strict filter against Designer, PM, QA, Odoo)
"""

from typing import Any
from job_bot.models import UserProfile


class JobMatchScore:
    """Detailed score breakdown for a job listing."""

    def __init__(
        self,
        job_id: str,
        total_score: int,
        reasons: list[str],
        tech_matches: list[str],
        is_disqualified: bool = False,
        disqualification_reason: str | None = None,
    ):
        self.job_id = job_id
        self.total_score = total_score
        self.reasons = reasons
        self.tech_matches = tech_matches
        self.is_disqualified = is_disqualified
        self.disqualification_reason = disqualification_reason


class JobMatcher:
    """Scores and ranks jobs to maximize interview callback rates."""

    DISQUALIFYING_ROLES = [
        "designer",
        "product manager",
        "sales",
        "marketing",
        "qa",
        "quality assurance",
        "test engineer",
        "sdet",
        "recruiter",
        "talent",
        "odoo",
        "flutter",
        "ios developer",
        "android developer",
        "mobile developer",
        "mobile app",
    ]

    TECH_WEIGHTS = {
        "fastapi": 20,
        "python": 18,
        "c++": 18,
        "rag": 16,
        "backend": 15,
        "vector": 12,
        "distributed": 12,
        "telemetry": 12,
        "redis": 10,
        "mysql": 8,
        "postgresql": 8,
        "postgis": 10,
        "ai": 10,
        "agent": 10,
        "spring boot": 8,
        "java": 6,
        "fullstack": 8,
        "data engineer": 10,
    }

    def __init__(self, profile: UserProfile):
        self.profile = profile

    def score_job(self, job_dict: dict[str, Any]) -> JobMatchScore:
        """Scores a job dictionary from DB (or JobListing) between 0 and 100."""
        title = (job_dict.get("title") or "").lower()
        loc = (job_dict.get("location") or "").lower()
        desc = (job_dict.get("description") or "").lower()
        job_id = job_dict.get("id") or ""

        # 1. Role Disqualifiers
        for d in self.DISQUALIFYING_ROLES:
            if d in title:
                return JobMatchScore(
                    job_id=job_id,
                    total_score=0,
                    reasons=[],
                    tech_matches=[],
                    is_disqualified=True,
                    disqualification_reason=f"Role mismatch: {d}",
                )

        # 2. Location Eligibility
        import re
        has_india_city = any(kw in loc for kw in ["pune", "bengaluru", "bangalore", "gurugram", "delhi", "hyderabad", "noida", "mumbai", "india"])
        has_india_code = bool(re.search(r"\b(in|ind)\b", loc, re.IGNORECASE))
        is_india = has_india_city or has_india_code
        is_remote = "remote" in loc or "anywhere" in loc or "worldwide" in loc
        is_us_onsite = (
            any(us_term in loc for us_term in ["united states", "san francisco", "palo alto", "seattle", "new york", "los angeles", "austin", "boston"])
            or bool(re.search(r"\b(us|usa)\b", loc, re.IGNORECASE))
        ) and not is_india and not is_remote

        if is_us_onsite:
            return JobMatchScore(
                job_id=job_id,
                total_score=0,
                reasons=[],
                tech_matches=[],
                is_disqualified=True,
                disqualification_reason="Requires US onsite / US work authorization",
            )

        score = 0
        reasons = []

        # Location scoring (max 25 pts)
        if "pune" in loc:
            score += 25
            reasons.append("Local in Pune (+25)")
        elif is_india:
            score += 20
            reasons.append("India location (+20)")
        elif is_remote:
            score += 15
            reasons.append("Global Remote (+15)")

        # 3. Technical Stack Overlap (max 45 pts)
        matched_tech = []
        tech_score = 0
        search_corpus = f"{title} {desc}"
        for tech, weight in self.TECH_WEIGHTS.items():
            if tech in search_corpus:
                tech_score += weight
                matched_tech.append(tech)
        tech_score = min(tech_score, 45)
        score += tech_score
        if matched_tech:
            reasons.append(f"Tech Match (+{tech_score}): {', '.join(matched_tech[:4])}")

        # 4. Experience Level Fit (max 20 pts)
        senior_penalty = any(term in title for term in ["staff", "principal", "director", "head of", "vp", "lead designer", "engineering lead"])
        if senior_penalty:
            score -= 20
            reasons.append("Seniority penalty (-20, requires 8+ YOE)")
        elif any(term in title for term in ["founding", "software engineer", "backend engineer", "applied ai", "engineer ii", "software engineer - 2", "software engineer 2", "sde 2", "sde ii"]):
            score += 20
            reasons.append("Target YOE match (+20, 1-3 yrs)")
        elif any(term in title for term in ["senior"]):
            score += 10
            reasons.append("Startup Senior match (+10)")
        else:
            score += 10
            reasons.append("General Engineer (+10)")

        # 5. Salary incentive (max 10 pts)
        min_lpa = job_dict.get("min_lpa") or 0.0
        max_lpa = job_dict.get("max_lpa") or 0.0
        currency = job_dict.get("currency") or "INR"
        if currency == "USD" or max_lpa >= 20.0 or min_lpa >= 15.0:
            score += 10
            reasons.append("High compensation tier (+10)")
        elif max_lpa >= 13.0 or min_lpa >= 12.0:
            score += 5
            reasons.append("Meets salary threshold (+5)")

        final_score = max(0, min(100, score))
        return JobMatchScore(
            job_id=job_id,
            total_score=final_score,
            reasons=reasons,
            tech_matches=matched_tech,
            is_disqualified=False,
        )

    def rank_jobs(self, jobs: list[dict[str, Any]], limit: int | None = None) -> list[tuple[dict[str, Any], JobMatchScore]]:
        """Ranks jobs by selection probability score in descending order."""
        scored = []
        for job in jobs:
            match_score = self.score_job(job)
            if not match_score.is_disqualified and match_score.total_score > 0:
                scored.append((job, match_score))

        scored.sort(key=lambda x: x[1].total_score, reverse=True)
        if limit and limit > 0:
            return scored[:limit]
        return scored
