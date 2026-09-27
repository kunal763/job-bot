"""Profile vault loader and validator for candidate information."""

import json
from pathlib import Path
from job_bot.config import config
from job_bot.models import UserProfile


class ProfileVault:
    """Loads, validates, and manages candidate profile data."""

    def __init__(self, profile_path: Path | None = None):
        self.profile_path = profile_path or config.profile_path
        self._profile: UserProfile | None = None

    def load(self) -> UserProfile:
        """Loads and validates the profile JSON file."""
        if not self.profile_path.exists():
            raise FileNotFoundError(
                f"Profile file not found at: {self.profile_path}. "
                f"Please copy profile.json.example to profile.json and fill in your details."
            )

        with open(self.profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        profile = UserProfile.model_validate(data)

        # Validate resume path exists
        resume_path = profile.documents.resume_path
        if not resume_path.is_absolute():
            resume_path = self.profile_path.parent / resume_path

        if not resume_path.exists():
            raise FileNotFoundError(
                f"Resume file not found at: {resume_path}. Please provide a valid PDF resume path."
            )

        # Update to resolved absolute path
        profile.documents.resume_path = resume_path.resolve()
        self._profile = profile
        return profile

    @property
    def profile(self) -> UserProfile:
        if self._profile is None:
            return self.load()
        return self._profile

    def get_skill_experience(self, skill_name: str) -> float:
        """Heuristic for years of experience with a given skill."""
        # By default, if the skill is listed in user's skills, return total years of experience
        # or customize in profile.json
        user_skills = [s.lower() for s in self.profile.career.skills]
        if any(skill_name.lower() in s or s in skill_name.lower() for s in user_skills):
            return self.profile.career.total_years_experience
        return 0.0

    def get_common_answer(self, query: str) -> str | None:
        """Check common predefined answers from profile."""
        q_lower = query.lower()
        answers = self.profile.common_answers
        for key, val in answers.items():
            if key.replace("_", " ") in q_lower or q_lower in key.replace("_", " "):
                return val
        return None
