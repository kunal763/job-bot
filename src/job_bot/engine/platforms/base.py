"""Abstract Base Class for job platforms (LinkedIn, Naukri, Indeed, etc.)."""

from abc import ABC, abstractmethod
from playwright.async_api import Page
from job_bot.models import JobListing


class JobPlatform(ABC):
    """Abstract platform interface."""

    def __init__(self, page: Page):
        self.page = page

    @abstractmethod
    async def search_jobs(
        self,
        keywords: list[str],
        location: str = "India",
        limit: int = 15,
        easy_apply_only: bool = True,
    ) -> list[JobListing]:
        """Search and extract job listings from the platform."""
        pass

    @abstractmethod
    async def apply_to_job(self, job: JobListing, dry_run: bool = True) -> tuple[bool, str]:
        """Fill and submit (or dry-run review) application for a job.

        Returns:
            (success: bool, status_message: str)
        """
        pass
