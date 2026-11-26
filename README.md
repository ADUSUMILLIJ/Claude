# Job search (JobSpy + Claude Code)

- **`/jobs`** — fresh, resume-matched supply-chain jobs from Indeed, Greenhouse, Lever, Workday and Ashby.
  Posted today, US, full-time/contract, ≤3 yrs experience, OPT/STEM-safe, direct ATS links, and it
  **never repeats** a job already shown (`data/seen_jobs.csv`).
- `scripts/job_search.py` — the pipeline behind `/jobs` (settings in `config/profile.json`,
  company boards in `data/ats_slugs.txt`). Output: `jobs/fresh_jobs_<timestamp>.xlsx/.csv`.
- `scripts/fetch_jobs.py` — simple generic JobSpy search for any title/location.

```bash
pip install -r requirements.txt
python3 scripts/job_search.py                       # default search
python3 scripts/job_search.py --terms "buyer" "demand planner"
python3 scripts/job_search.py --include-seen        # show previously given jobs too
```
