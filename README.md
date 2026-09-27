# 🤖 Job Bot: Autonomous Multi-Site Job Seeker & Application Agent

An intelligent, modular automation system that periodically scans job boards (starting with **LinkedIn Easy Apply**), filters listings based on strict criteria (minimum **12–13 LPA** salary and tech stack alignment), and autonomously fills out application forms using a localized profile vault and LLM assistance for custom application questions.

---

## 🏗️ System Architecture

```text
[ Job Sources: LinkedIn Easy Apply ] 
                 │
                 ▼
[ Ingestion & Filtering Engine ] ────────(Saves match)────────> [ SQLite Database: job_bot.db ]
  • Regex Salary Normalizer (12+ LPA)                                    │
  • Deduplication layer                                                  │
                 │                                                       │
                 ▼                                                       ▼
[ Profile Vault: profile.json ] ─────────────────────────> [ Form Filling Engine ]
  • Personal / Contact Info                                  • Multi-step modal stepper
  • Experience & CTC fields                                  • Smart Label-to-input mapper
  • Resume PDF attachment                                    • Dry-run safety mode
                                                                         │
                                                                         ▼
                                                           [ AI Copilot: Groq / Gemini ]
                                                             • Subjective form questions
                                                             • Experience heuristics
                                                             • Question-Answer Caching
```

---

## ⚡ Core Features

1. **Strict 12+ LPA Salary Normalization:**
   - Multi-format regex engine handles:
     - `12 - 18 LPA`, `15 Lacs P.A.`, `₹15,00,000 / year`
     - Monthly conversions: `₹1,00,000 / month` $\to$ `12.0 LPA`
     - USD conversion: `$100k / year` $\to$ `~86.0 LPA`
   - Configurable minimum threshold (`MIN_SALARY_LPA=12.0`) and unlisted salary policy.

2. **Persistent Browser Session (No Frequent Logins):**
   - Uses Playwright persistent browser contexts in `data/browser_context/`.
   - Log in once with `job-bot login`, and session cookies are preserved across all subsequent runs.
   - Built-in stealth flags (`navigator.webdriver` removal, realistic user agent).

3. **Smart Label-to-Input Form Filler:**
   - Heuristically maps text inputs, dropdown selects, textareas, and radio buttons.
   - Automatically handles resume PDF attachment from your profile vault.
   - **Dry Run Mode:** Traverses through every step, fills answers, and stops before the final "Submit" button to verify everything safely.

4. **AI Copilot (Groq & Gemini Support):**
   - Resolves dynamic or open-ended questions using Groq (`llama-3.3-70b-versatile`) or Google Gemini (`gemini-2.5-flash`).
   - Built-in deterministic heuristics for experience, notice periods, and CTC.
   - **QA Caching:** Previously answered questions are stored in SQLite to avoid redundant LLM queries.

5. **Deduplication & Application Tracking:**
   - Tracks listings and status (`QUEUED`, `APPLIED`, `FILTERED_OUT`, `FAILED`, `REVIEW_NEEDED`).
   - Prevents duplicate applications to the same listing.

---

## 🚀 Quickstart

### 1. Setup Environment
Ensure you have `uv` installed. If not, install via:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Sync project dependencies and install the CLI:
```bash
uv sync
uv pip install -e .
```

### 2. Configure Profile & Keys
Copy the example templates:
```bash
cp profile.json.example profile.json
cp .env.example .env
```

1. Edit `profile.json` with your real contact info, career details, and resume PDF path.
2. (Optional) In `.env`, add your `GROQ_API_KEY` (Free tier from [console.groq.com](https://console.groq.com)) or `GEMINI_API_KEY`.

---

## 🛠️ CLI Usage

### 1. Persistent Login (One-time setup)
Open an interactive browser to log into your LinkedIn account. Session cookies will be saved in `data/browser_context`:
```bash
uv run job-bot login
```

### 2. Validate Profile Vault
Verify that your profile schema is valid and your resume file exists:
```bash
uv run job-bot profile
```

### 3. Search & Filter (>= 12 LPA)
Search LinkedIn Easy Apply for jobs matching your criteria:
```bash
# Search for Python Developer roles in India with >= 12 LPA
uv run job-bot search --keyword "Python" --keyword "Backend" --location "India" --min-lpa 12.0
```

### 4. Apply (with Dry-Run Safety)
Run the form filler on discovered jobs:
```bash
# Safe dry run: validates all form fields without submitting
uv run job-bot apply --dry-run

# Live submission: submits the application
uv run job-bot apply --live
```

### 5. Full Autonomous Pipeline
Run discovery, filtering, and application in a single command:
```bash
uv run job-bot run --keyword "Python" --location "India" --min-lpa 12.0 --dry-run
```

### 6. Track Applications & DB Stats
Inspect tracked jobs and summary stats:
```bash
uv run job-bot db stats
uv run job-bot db --status QUEUED
uv run job-bot db --status APPLIED
```

---

## 🧪 Testing

Run the automated test suite covering salary parsing, profile validation, SQLite operations, AI copilot, and DOM form filling:
```bash
uv run pytest
```
