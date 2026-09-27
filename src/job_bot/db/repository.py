"""Database repository for jobs, applications, and question-answer caching."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from job_bot.config import config
from job_bot.models import ApplicationRecord, ApplicationStatus, JobListing, SalaryInfo


class JobRepository:
    """Manages SQLite operations for job persistence and deduplication."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or config.db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Run schema migrations."""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self._get_connection() as conn:
            conn.executescript(schema_sql)

    def is_job_processed(self, job_id: str) -> bool:
        """Check if job exists in database already (to avoid re-evaluating or duplicate applies)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,))
            return cursor.fetchone() is not None

    def save_job(self, job: JobListing, initial_status: ApplicationStatus = ApplicationStatus.DISCOVERED) -> None:
        """Save or update job details and its initial application record."""
        with self._get_connection() as conn:
            min_lpa = job.salary_info.min_lpa if job.salary_info else None
            max_lpa = job.salary_info.max_lpa if job.salary_info else None
            currency = job.salary_info.currency if job.salary_info else "INR"

            conn.execute(
                """
                INSERT INTO jobs (id, platform, external_job_id, title, company, location, salary_raw, min_lpa, max_lpa, currency, url, description, easy_apply, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    company=excluded.company,
                    location=excluded.location,
                    salary_raw=excluded.salary_raw,
                    min_lpa=excluded.min_lpa,
                    max_lpa=excluded.max_lpa,
                    description=excluded.description,
                    easy_apply=excluded.easy_apply
                """,
                (
                    job.id,
                    job.platform,
                    job.external_job_id,
                    job.title,
                    job.company,
                    job.location,
                    job.salary_raw,
                    min_lpa,
                    max_lpa,
                    currency,
                    job.url,
                    job.description,
                    1 if job.easy_apply else 0,
                    job.scraped_at.isoformat(),
                ),
            )

            conn.execute(
                """
                INSERT INTO applications (job_id, status, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = CASE 
                        WHEN applications.status = 'FILTERED_OUT' AND excluded.status = 'QUEUED' THEN 'QUEUED' 
                        ELSE applications.status 
                    END,
                    updated_at = excluded.updated_at
                """,
                (job.id, initial_status.value, datetime.now(timezone.utc).isoformat()),
            )

    def update_job_company(self, job_id: str, company: str) -> None:
        """Update authentic company name for a job."""
        with self._get_connection() as conn:
            conn.execute("UPDATE jobs SET company = ? WHERE id = ?", (company, job_id))

    def update_application_status(
        self,
        job_id: str,
        status: ApplicationStatus,
        notes: str | None = None,
        error_message: str | None = None,
        custom_answers: dict[str, Any] | None = None,
    ) -> None:
        """Update status and timestamps for an application."""
        applied_at = datetime.now(timezone.utc).isoformat() if status == ApplicationStatus.APPLIED else None
        custom_answers_json = json.dumps(custom_answers) if custom_answers is not None else None

        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE applications
                SET status = ?,
                    applied_at = COALESCE(?, applied_at),
                    notes = COALESCE(?, notes),
                    error_message = COALESCE(?, error_message),
                    custom_answers_json = COALESCE(?, custom_answers_json),
                    updated_at = ?
                WHERE job_id = ?
                """,
                (
                    status.value,
                    applied_at,
                    notes,
                    error_message,
                    custom_answers_json,
                    datetime.now(timezone.utc).isoformat(),
                    job_id,
                ),
            )

    def get_applications(self, status: ApplicationStatus | None = None) -> list[dict[str, Any]]:
        """Retrieve applications with their corresponding job info."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = """
                SELECT j.*, a.status, a.applied_at, a.notes, a.error_message, a.custom_answers_json, a.updated_at
                FROM jobs j
                JOIN applications a ON j.id = a.job_id
            """
            params: list[Any] = []
            if status:
                query += " WHERE a.status = ?"
                params.append(status.value)
            query += " ORDER BY a.updated_at DESC"
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_cached_answer(self, question: str) -> str | None:
        """Find cached LLM answer for a normalized form question."""
        norm = self._normalize_question(question)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT answer FROM qa_cache WHERE question_normalized = ?", (norm,))
            row = cursor.fetchone()
            return row["answer"] if row else None

    def cache_answer(self, question: str, answer: str, source: str = "llm") -> None:
        """Cache a question answer to avoid repetitive LLM calls."""
        norm = self._normalize_question(question)
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO qa_cache (question_normalized, answer, source, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(question_normalized) DO UPDATE SET
                    answer=excluded.answer,
                    source=excluded.source
                """,
                (norm, answer, source, datetime.now(timezone.utc).isoformat()),
            )

    @staticmethod
    def _normalize_question(text: str) -> str:
        """Standardize question text for cache lookup."""
        import re
        # remove punctuation, lower-case, collapse whitespace
        cleaned = re.sub(r"[^\w\s]", "", text.lower())
        return " ".join(cleaned.split())
