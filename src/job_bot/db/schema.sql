-- SQLite schema for Job Bot

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    external_job_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    salary_raw TEXT,
    min_lpa REAL,
    max_lpa REAL,
    currency TEXT DEFAULT 'INR',
    url TEXT NOT NULL,
    description TEXT,
    easy_apply INTEGER DEFAULT 1,
    scraped_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL,
    applied_at TEXT,
    notes TEXT,
    error_message TEXT,
    custom_answers_json TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS qa_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_normalized TEXT UNIQUE NOT NULL,
    answer TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs(platform);
CREATE INDEX IF NOT EXISTS idx_jobs_min_lpa ON jobs(min_lpa);
CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);
