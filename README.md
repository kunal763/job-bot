# 🤖 Job Bot: Autonomous Multi-Site Job Seeker & Application Agent

An intelligent, modular automation system that scans startup and tech job platforms (**LinkedIn**, **Wellfound / AngelList**, and **Y Combinator's Work at a Startup**), filters listings based on strict criteria (minimum **12–13+ LPA** salary and tech stack alignment), and autonomously applies with AI-tailored pitches and form filling.

---

## 🏗️ System Architecture

```text
[ Job Sources: LinkedIn Easy Apply | Wellfound | Y Combinator (Work at a Startup) ] 
                                      │
                                      ▼
[ Ingestion & Filtering Engine ] ────────(Saves match)────────> [ SQLite Database: job_bot.db ]
  • Regex Salary Normalizer (13+ LPA)                                    │
  • INR Millions, Lakhs, USD Conversion                                  │
  • Deduplication & Tech Stack Matcher                                    │
                                      │                                  │
                                      ▼                                  ▼
[ Profile Vault: profile.json ] ─────────────────────────> [ Form Filling Engine ]
  • Personal / Contact Info                                  • LinkedIn Easy Apply stepper
  • Experience & CTC fields                                  • Wellfound Quick Apply
  • Portfolio: kunal763.github.io                            • YC founder pitch note & ATS filler
  • Resume PDF attachment                                    • Dry-run safety mode
                                                                         │
                                                                         ▼
                                                           [ AI Copilot: Groq / Gemini ]
                                                             • Subjective form questions
                                                             • Founder pitch generation
                                                             • Question-Answer Caching
```

---

## ⚡ Core Features

1. **Multi-Platform Startup Integration:**
   - **Y Combinator (Work at a Startup):** Direct search across YC batch companies, salary range parsing, external ATS detection (Greenhouse/Lever/Ashby), and AI-generated pitches to founders.
   - **Wellfound (AngelList Talent):** Role-slug discovery, salary parsing, relocation handling, and autonomous Quick Apply modal completion.
   - **LinkedIn Easy Apply:** Automated modal traversal, question answering, and resume attachment.

2. **Strict 13+ LPA Salary Normalization:**
   - Handles multi-format salary standards:
     - YC INR Millions: `₹2M - ₹4M INR` $\to$ `20.0 - 40.0 LPA`
     - YC Short INR: `₹25 - ₹35 INR` $\to$ `25.0 - 35.0 LPA`
     - Explicit Lakhs: `12 - 18 LPA`, `15 Lacs P.A.`, `₹15,00,000 / year`
     - Monthly: `₹1,00,000 / month` $\to$ `12.0 LPA`
     - Global USD: `$90K - $130K` $\to$ `77.4 - 111.8 LPA`

3. **Persistent Browser Session:**
   - Saved in `data/browser_context/`.
   - Log in once with `uv run job-bot login --platform yc` (or `linkedin`, `wellfound`), or attach to Chrome via CDP (`--cdp`).

4. **AI Pitch Generator (Groq Llama-3.3):**
   - Automatically writes authentic, highly tailored pitches to startup founders highlighting real engineering accomplishments.

---

## 🛠️ CLI Usage

### 1. Platform Login (One-time setup)
```bash
# Log into Y Combinator Work at a Startup
uv run job-bot login --platform yc

# Log into Wellfound
uv run job-bot login --platform wellfound

# Log into LinkedIn
uv run job-bot login --platform linkedin
```

### 2. Search & Filter (>= 13 LPA)
```bash
# Search Y Combinator startups for Python and Backend separately
uv run job-bot search --platform yc -k Python -k Backend -l India -m 13.0 -n 10 --separate

# Search across all platforms
uv run job-bot search --platform all -k Python -l India -m 13.0 -n 10
```

### 3. Apply (with Dry-Run Safety)
```bash
# Safe dry run: verifies job details and generates tailored founder pitch
uv run job-bot apply --platform yc --dry-run --limit 5

# Live application: submits directly to YC startups
uv run job-bot apply --platform yc --live --limit 10
```

### 4. End-to-End Autonomous Run
```bash
# Search and apply to YC startups >= 13 LPA in a single run
uv run job-bot run --platform yc -k Python -k Backend -l India -m 13.0 -n 10 --separate --dry-run
```

### 5. Track Applications & DB Stats
```bash
uv run job-bot db stats
uv run job-bot db list --status QUEUED
uv run job-bot db list --status APPLIED
```

---

## 🧪 Testing

Run the full automated test suite (26 tests):
```bash
uv run pytest
```

