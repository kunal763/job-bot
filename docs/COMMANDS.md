# 📖 Job Bot Complete CLI Command Reference & Cheatsheet

> **Note on Execution:**
> * **On Laptop / Desktop:** Use `uv run job-bot <command>` (or `job-bot <command>` if your virtual environment is active).
> * **On Android Phone (Termux):** Use `jobbot <command>` (which automatically proxies to `job-bot` inside the PRoot Ubuntu container).

---

## 📑 Table of Contents
1. [Core Daily Workflow (The 3-Step Routine)](#-core-daily-workflow)
2. [Job Search & Discovery (`search`)](#1-job-search--discovery-search)
3. [AI Matching & Probability Ranking (`rank`)](#2-ai-matching--probability-ranking-rank)
4. [Job Application Engine (`apply`)](#3-job-application-engine-apply)
5. [End-to-End Autonomous Cycle (`run`)](#4-end-to-end-autonomous-cycle-run)
6. [External ATS Applications (`apply-external`)](#5-external-ats-applications-apply-external)
7. [Database & Application Tracking (`db`)](#6-database--application-tracking-db)
8. [Session Authentication & Setup (`login`, `set-cookie`, `launch-chrome`)](#7-session-authentication--setup)
9. [Profile Vault Inspection (`profile`)](#8-profile-vault-inspection-profile)
10. [Wellfound Profile Auto-Optimizer (`update-wellfound-profile`)](#9-wellfound-profile-auto-optimizer-update-wellfound-profile)
11. [Telegram Mobile Remote Control (`telegram-bot`)](#10-telegram-mobile-remote-control-telegram-bot)

---

## ⚡ Core Daily Workflow

Follow this standard 3-step routine to find and apply to the best matching jobs every day:

```bash
# 1. Scrape latest matching roles into database
uv run job-bot search --platform yc --keyword "Python" --keyword "Backend" --limit 20 --headless

# 2. View top-scored opportunities ranked by hiring probability
uv run job-bot rank --platform yc --limit 5

# 3. Dry-run verify application (fills forms & AI pitch, does NOT submit)
uv run job-bot apply --platform yc --limit 5 --headless

# 4. Submit official live applications to founders
uv run job-bot apply --platform yc --live --limit 5 --headless
```

---

## 1. Job Search & Discovery (`search`)

Scrapes target platforms, normalizes salaries (currency conversion & LPA evaluation), checks technical qualification, and queues matching listings into the SQLite database.

```bash
uv run job-bot search [OPTIONS]
```

### Options & Flags
| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `--platform` | `-p` | `all` | Target platform: `yc`, `wellfound`, `linkedin`, or `all` |
| `--keyword` | `-k` | `Python`, `Developer` | Keywords to search (repeat flag to specify multiple) |
| `--location` | `-l` | `India` | Geographical target location (e.g. `India`, `Remote`, `Bengaluru`) |
| `--min-lpa` | `-m` | `12.0` | Minimum salary cutoff in Lakhs Per Annum (LPA) |
| `--allow-unlisted` | | `False` | Also queue startup jobs that don't list explicit salary ranges |
| `--limit` | `-n` | `10` | Maximum jobs to scrape per keyword batch |
| `--headless` | | `False` | Run browser invisibly (recommended on server / mobile) |
| `--separate` / `--combined` | | `--separate` | Search each keyword individually vs. combined into one phrase |

### Common Examples
```bash
# Search YC for Python and Backend jobs in India/Remote (20 per keyword)
uv run job-bot search --platform yc -k "Python" -k "Backend" --limit 20 --headless

# Search YC including unlisted salary listings
uv run job-bot search --platform yc -k "Python" --allow-unlisted --limit 15 --headless

# Search Wellfound for Fullstack / AI engineer roles with 15+ LPA filter
uv run job-bot search --platform wellfound -k "Fullstack" -k "AI" --min-lpa 15 --headless

# Search all platforms for Backend roles
uv run job-bot search --platform all -k "Backend" --limit 10 --headless
```

---

## 2. AI Matching & Probability Ranking (`rank`)

Evaluates all `QUEUED` jobs in the database against your resume skills, experience, and achievements using the `JobMatcher` scoring engine (scored 0–100 with advantage reasons).

```bash
uv run job-bot rank [OPTIONS]
```

### Options & Flags
| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `--platform` | `-p` | `yc` | Platform filter: `yc`, `wellfound`, or `linkedin` |
| `--limit` | `-n` | `5` | Number of top-ranked jobs to display |
| `--min-lpa` | `-m` | `None` | Optional salary filter in LPA |

### Common Examples
```bash
# View top 5 highest-probability YC jobs
uv run job-bot rank --platform yc --limit 5

# View top 10 roles across Wellfound
uv run job-bot rank --platform wellfound --limit 10

# Filter ranked results to roles paying >= 18 LPA
uv run job-bot rank --platform yc --min-lpa 18 --limit 5
```

---

## 3. Job Application Engine (`apply`)

Automatically re-ranks candidate jobs, opens the application modal, fills all fields with your Profile Vault data, generates customized founder pitches via Groq AI Copilot, and submits.

```bash
uv run job-bot apply [OPTIONS]
```

### Options & Flags
| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `--platform` | `-p` | `None` | Filter by platform: `yc`, `wellfound`, `linkedin`, or all |
| `--dry-run` / `--live` | | `--dry-run` | **Safety Mode:** `--dry-run` fills forms without final submit. `--live` officially submits |
| `--limit` | `-n` | `None` | Maximum jobs to process (e.g. top 5) |
| `--job-id` | `-j` | `None` | Apply to one specific Job ID from the database |
| `--min-lpa` | `-m` | `None` | Minimum salary filter in LPA |
| `--allow-unlisted` | | `False` | Allow applying to jobs with unlisted salary |
| `--headless` | | `False` | Run browser in headless mode without UI window |

### Common Examples
```bash
# Dry-run top 5 YC applications (safe testing)
uv run job-bot apply --platform yc --limit 5 --headless

# Officially submit live applications to top 5 YC startups
uv run job-bot apply --platform yc --live --limit 5 --headless

# Apply to a single specific job ID from the database
uv run job-bot apply --job-id yc_103118 --live --headless

# Apply to top 3 Wellfound jobs in live mode
uv run job-bot apply --platform wellfound --limit 3 --live --headless
```

---

## 4. End-to-End Autonomous Cycle (`run`)

Combines **Search ➔ Filter ➔ Deduplicate ➔ Rank ➔ Apply** into a single autonomous command.

```bash
uv run job-bot run [OPTIONS]
```

### Options & Flags
| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `--platform` | `-p` | `all` | Target platform (`all`, `yc`, `wellfound`, `linkedin`) |
| `--keyword` | `-k` | `Python`, `Backend` | Target keywords |
| `--location` | `-l` | `India` | Target location |
| `--min-lpa` | `-m` | `12.0` | Minimum salary cutoff |
| `--limit` | `-n` | `10` | Jobs to scout and apply to |
| `--dry-run` / `--live` | | `--dry-run` | Safety mode |
| `--headless` | | `False` | Run browser in headless mode |

### Common Examples
```bash
# Full autonomous cycle on YC in safe dry-run mode
uv run job-bot run --platform yc -k "Python" -k "Backend" --limit 5 --headless

# Full autonomous cycle on YC in live mode
uv run job-bot run --platform yc -k "Python" -k "Backend" --limit 5 --live --headless
```

---

## 5. External ATS Applications (`apply-external`)

Autofills external ATS job portals (such as **Greenhouse**, **Lever**, **Ashby**, **Workable**) using the AI Copilot.

```bash
uv run job-bot apply-external <JOB_URL> [OPTIONS]
```

### Options & Flags
| Option / Flag | Short | Default | Description |
| :--- | :---: | :---: | :--- |
| `url` | *(arg)* | *(required)* | URL of the job application page |
| `--resume` | `-r` | `None` | Path to custom PDF resume (defaults to Profile Vault resume) |
| `--dry-run` / `--live` | | `--dry-run` | Test form fill vs. submit application |
| `--headless` | | `False` | Run browser in headless mode |

### Common Examples
```bash
# Test filling a Greenhouse job application
uv run job-bot apply-external "https://boards.greenhouse.io/company/jobs/12345"

# Submit live application on Ashby
uv run job-bot apply-external "https://jobs.ashbyhq.com/company/abc-123" --live --headless
```

---

## 6. Database & Application Tracking (`db`)

Inspect tracked applications, check history, and review platform performance.

### A. List Applications (`db list`)
```bash
uv run job-bot db list [OPTIONS]
```
| Option / Flag | Short | Description |
| :--- | :---: | :--- |
| `--status` | `-s` | Filter status: `QUEUED`, `APPLIED`, `FAILED`, `SKIPPED`, `FILTERED_OUT` |

```bash
# View all currently queued jobs ready to be processed
uv run job-bot db list --status QUEUED

# View all successfully applied jobs
uv run job-bot db list --status APPLIED

# View all failed applications and error notes
uv run job-bot db list --status FAILED
```

### B. Summary Statistics (`db stats`)
Displays total tracked jobs, breakdown by status, and breakdown by platform:
```bash
uv run job-bot db stats
```

---

## 7. Session Authentication & Setup

Manages persistent browser cookies and browser profiles so you never have to log in repeatedly.

### A. Interactive Platform Login (`login`)
Opens a visible browser window to log in once; pressing `ENTER` in the terminal persists your cookies to `data/browser_context/`:
```bash
# Log into Y Combinator (Work at a Startup)
uv run job-bot login --platform yc

# Log into Wellfound
uv run job-bot login --platform wellfound

# Log into LinkedIn
uv run job-bot login --platform linkedin
```

### B. Launch Real Chrome with Remote Debugging (`launch-chrome`)
Launches your local system Google Chrome on port `9222`:
```bash
uv run job-bot launch-chrome --port 9222
```

### C. Direct Cookie Injection (`set-cookie`)
Manually set your LinkedIn `li_at` cookie:
```bash
uv run job-bot set-cookie "AQEDAT..."
```

---

## 8. Profile Vault Inspection (`profile`)

Displays the parsed personal details, contact info, current/expected compensation, notice period, technical skills, and resume path currently active in `profile.json`:

```bash
uv run job-bot profile
```

---

## 9. Wellfound Profile Auto-Optimizer (`update-wellfound-profile`)

Automatically logs into Wellfound and populates your profile with an optimized bio elevator pitch, social links, brag sheet of projects & achievements, work experience, and core skills:

```bash
# Optimize Wellfound profile in headless mode
uv run job-bot update-wellfound-profile

# Watch visually in browser window
uv run job-bot update-wellfound-profile --no-headless
```

---

## 10. Telegram Mobile Remote Control (`telegram-bot`)

Launches a 24/7 background listener enabling you to trigger searches, rankings, and applications directly from your phone via Telegram:

```bash
uv run job-bot telegram-bot
```

### Optional Flags
* `--token` / `-t`: Telegram bot API token (if not set in `.env`)
* `--chat-id` / `-c`: Authorized Telegram chat ID (if not set in `.env`)

---

## 📱 Quick Comparison: Laptop vs. Mobile (Termux)

| Action | Laptop Command | Phone (Termux) Command |
| :--- | :--- | :--- |
| **Search YC** | `uv run job-bot search --platform yc -k "Python" --headless` | `jobbot search --platform yc -k "Python" --headless` |
| **Rank Top 5** | `uv run job-bot rank --platform yc --limit 5` | `jobbot rank --platform yc --limit 5` |
| **Dry Run Apply** | `uv run job-bot apply --platform yc --limit 5 --headless` | `jobbot apply --platform yc --limit 5 --headless` |
| **Live Apply** | `uv run job-bot apply --platform yc --live --limit 5 --headless` | `jobbot apply --platform yc --live --limit 5 --headless` |
| **Check Stats** | `uv run job-bot db stats` | `jobbot db stats` |
| **List Queued** | `uv run job-bot db list --status QUEUED` | `jobbot db list --status QUEUED` |
