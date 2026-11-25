# Job postings fetcher (JobSpy + Claude Code)

- `/jobs <title> in <location> ...` — Claude Code slash command (`.claude/commands/jobs.md`)
- `scripts/fetch_jobs.py` — standalone CLI; results saved to `jobs/*.csv` and `.json`

```bash
pip install -r requirements.txt
python3 scripts/fetch_jobs.py -s "data analyst" -l "Boston, MA" --sites indeed linkedin -n 30 --hours 48
```

Flags: `--remote`, `--job-type fulltime|parttime|internship|contract`, `--country`, `--description`, `--outdir`.
ZipRecruiter/Glassdoor may return 403 from cloud IPs; they usually work from a home network.
