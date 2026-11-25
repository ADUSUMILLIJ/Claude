---
description: Fetch job postings with JobSpy (Indeed, LinkedIn, Google, ZipRecruiter, Glassdoor)
argument-hint: <job title> [in <location>] [remote] [last N hours] [N results] [sites ...]
allowed-tools: Bash(python3 scripts/fetch_jobs.py:*), Bash(pip install:*), Read
---

Fetch job postings for: **$ARGUMENTS**

1. Make sure JobSpy is installed: `python3 -c "import jobspy"`; if it fails, run `pip install -r requirements.txt`.
2. Parse the request into flags for `scripts/fetch_jobs.py`:
   - `--search` job title/keywords (required)
   - `--location` (default "United States"), `--remote`, `--hours` (default 72),
     `--results` per site (default 25), `--job-type fulltime|parttime|internship|contract`,
     `--sites` subset of indeed linkedin google zip_recruiter glassdoor
3. Run `python3 scripts/fetch_jobs.py ...`. If a site errors or is blocked, rerun without it.
4. Present a table of the best matches (title, company, location, posted date, salary if present, link),
   newest first, and give the path of the saved CSV/JSON in `jobs/`.
