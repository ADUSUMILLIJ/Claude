---
description: Fresh resume-matched supply-chain jobs (Indeed, Greenhouse, Lever, Workday, Ashby) — never repeats jobs already shown
argument-hint: "[optional extra search terms, e.g. demand planner, buyer] [include seen] [not today only]"
allowed-tools: Bash(python3 scripts/job_search.py:*), Bash(python3 scripts/fetch_jobs.py:*), Bash(pip install:*), Read, Edit
---

Find **fresh** jobs for me. Extra request: **$ARGUMENTS**

## My standing preferences (also in `config/profile.json` — keep both in sync if I change them)
- **Profile:** Supply Chain Analyst (resume: inventory management, demand forecasting, procurement, S&OP,
  supplier management, logistics; SAP/S4HANA, SQL, Python, Power BI, Tableau, Advanced Excel).
  MS Information Systems, Northeastern. **On OPT (STEM)**.
- **Market:** United States only. **Job type:** full-time or contract.
- **Freshness:** posted **today** only (original posting date checked on the ATS itself); **no reposts**.
- **Experience:** postings asking **≤ 3 years** (or not stated).
- **Sites:** only postings hosted on **Indeed** or applying through **Greenhouse, Lever, Workday, Ashby**.
- **Roles:** analyst / planner / buyer / procurement / sourcing / inventory / logistics / supply-chain
  specialist-coordinator roles. **Skip** clerk, warehouse, driver, forklift, handler, picker, technician,
  supervisor, manager, senior, sales and other non-matching roles.
- **OPT/STEM:** drop postings with ITAR/EAR, US-citizen/US-person, security-clearance, green-card or
  no-sponsorship wording; require STEM/IS evidence (SQL, ERP/SAP/Oracle, MRP, forecasting, BI tools, etc.);
  flag employers that state E-Verify in the posting, mark the rest "Verify".
- **Never repeat:** anything already shown lives in `data/seen_jobs.csv`; each run only returns new jobs
  and appends them there.

## Steps
1. Ensure deps: `python3 -c "import jobspy, openpyxl"` → if it fails, `pip install -r requirements.txt`.
2. Run `python3 scripts/job_search.py` (add `--terms "..." "..."` if I gave specific titles;
   `--include-seen` only if I ask to see old ones; `--no-today-only` if I ask for a wider window).
   It takes a few minutes (Workday date checks are rate-limited) — run it in the background and tell me it's running.
3. Reply with **plain direct URLs only** (one per line, grouped Strong / Good / Fair), plus a one-line
   count. Mention the saved `jobs/fresh_jobs_*.xlsx` file. Don't re-list anything from previous runs.
4. If a new ATS company board showed up in results, add its slug to `data/ats_slugs.txt`.
5. Commit `data/seen_jobs.csv` (and any slug additions) and push, so the memory persists across sessions.
