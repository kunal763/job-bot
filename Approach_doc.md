An approach document outlines the blueprint, technical architecture, data flow, and phased roadmap for your automated job seeker and application filler.

---

# Approach Document: Autonomous Multi-Site Job Seeker & Application Agent

## 1. Executive Summary

The objective of this project is to build an intelligent, modular automation system that periodically scans major job boards, filters listings based on strict criteria (minimum **12–13 LPA** salary, tech stack alignment), and autonomously fills out application forms using a localized profile vault and LLM assistance for custom application questions.

---

## 2. System Architecture & Components

The system is broken down into four core decoupled modules:

```
[ Job Sources / APIs ] 
         │
         ▼
[ 1. Ingestion & Filtering Engine ] ──(Saves match)──> [ SQLite Database ]
         │                                                      │
         ▼                                                      │
[ 2. Profile & Document Vault ]                                 │
         │                                                      │
         ▼                                                      ▼
[ 3. Browser Automation / Form Filler ] <───────────────────────┘
         │
         ▼
[ 4. AI Copilot / LLM Fallback ] (Handles custom text prompts)

```

### Module 1: Ingestion & Filtering Engine

* **Purpose:** Pulls job listings from target platforms or aggregators.
* **Salary Normalization:** Regular expression parsers and heuristics extract salary strings, convert hourly/monthly/lump-sum figures into an annual **LPA (Lakhs Per Annum)** format, and drop anything below the threshold.
* **Deduplication:** Checks the SQLite database to ensure the bot never applies to the same job twice.

### Module 2: Profile & Document Vault (`profile.json`)

* **Purpose:** Acts as the single source of truth for all personal, professional, and educational history.
* **Assets:** Stores paths to tailored resume PDFs (`.pdf`), cover letter templates, links to GitHub/LinkedIn/Portfolio, and standard numerical fields (Years of Experience, Notice Period, Expected CTC).

### Module 3: Browser Automation Engine (`Playwright`)

* **Purpose:** Handles navigation, clicking, authentication persistence, and DOM interaction.
* **Session Management:** Uses persistent browser contexts to maintain login cookies (bypassing frequent login screens for LinkedIn, Naukri, etc.).
* **Smart Selectors:** Utilizes label-to-input mapping (`aria-label`, placeholder text, and surrounding `<label>` text) rather than fragile CSS IDs.

### Module 4: AI Copilot & LLM Fallback

* **Purpose:** Resolves dynamic form anomalies and custom text inputs.
* **Behavior:** When an application form asks subjective questions (e.g., *"Describe a time you solved a complex scaling issue"*), the text is passed to an LLM along with the user's project history to generate a concise, professional response.

---

## 3. Step-by-Step Data Flow

1. **Initialization:** The script loads configuration files (`profile.json`) and establishes a connection to the local SQLite database.
2. **Discovery & Scraping:** Playwright opens a persistent browser session, navigates to target search URLs, and scrapes visible job cards.
3. **Evaluation Loop:**
* Extract Title, Company, Description, and Salary.
* Run `evaluate_salary()`. If $< 12 \text{ LPA}$, discard.
* Check database: If `job_id` exists, skip.


4. **Application Trigger:**
* Click "Apply" or "Easy Apply".
* Traverse form fields. Map known fields (Name, Email, Experience) directly from `profile.json`.
* For unknown fields or open-ended questions, invoke the LLM fallback.


5. **Submission & Logging:** Uploads the resume PDF, completes the final submission click, and logs the status as `Applied` in the database with a timestamp.

---

## 4. Phased Development Roadmap

| Phase | Milestone | Core Tasks |
| --- | --- | --- |
| **Phase 1** | **Scraping & Filtering Core** | Set up Playwright, build job card parsers, and implement robust regex salary extraction for 12+ LPA thresholds. |
| **Phase 2** | **Profile & DB Integration** | Build the `profile.json` structure and SQLite tracking layer to prevent duplicate applications. |
| **Phase 3** | **Form Filling Engine** | Implement label-based form filler for standard inputs (text boxes, dropdowns, file uploads for resumes). |
| **Phase 4** | **AI Fallback & Polish** | Integrate LLM API calls to answer custom application questions dynamically and add error handling/logging. |

---