#!/usr/bin/env python3
"""Fetch job postings with python-jobspy and save them to CSV/JSON.

Example:
  python scripts/fetch_jobs.py --search "data analyst" --location "Boston, MA" \
      --sites indeed linkedin --results 30 --hours 72
"""
import argparse
import datetime as dt
import pathlib
import sys

import pandas as pd
from jobspy import scrape_jobs

DEFAULT_SITES = ["indeed", "linkedin", "google", "zip_recruiter", "glassdoor"]
COLUMNS = ["site", "title", "company", "location", "date_posted", "job_type",
           "is_remote", "min_amount", "max_amount", "interval", "job_url"]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--search", "-s", required=True, help="Job title / keywords")
    p.add_argument("--location", "-l", default="United States")
    p.add_argument("--sites", nargs="+", default=DEFAULT_SITES, choices=DEFAULT_SITES + ["bayt", "naukri", "bdjobs"])
    p.add_argument("--results", "-n", type=int, default=25, help="Results wanted per site")
    p.add_argument("--hours", type=int, default=72, help="Only postings from the last N hours")
    p.add_argument("--remote", action="store_true", help="Remote jobs only")
    p.add_argument("--job-type", choices=["fulltime", "parttime", "internship", "contract"])
    p.add_argument("--country", default="USA", help="Country for Indeed/Glassdoor")
    p.add_argument("--description", action="store_true", help="Fetch full LinkedIn descriptions (slower)")
    p.add_argument("--outdir", default="jobs")
    a = p.parse_args()

    kwargs = dict(
        site_name=a.sites,
        search_term=a.search,
        google_search_term=f"{a.search} jobs near {a.location} since {max(1, a.hours // 24)} days ago",
        location=a.location,
        results_wanted=a.results,
        hours_old=a.hours,
        country_indeed=a.country,
        linkedin_fetch_description=a.description,
        is_remote=a.remote,
        verbose=1,
    )
    if a.job_type:
        kwargs["job_type"] = a.job_type

    df = scrape_jobs(**kwargs)
    if df is None or df.empty:
        print("No jobs found.")
        return 1

    df = df.drop_duplicates(subset=["job_url"])
    if "date_posted" in df:
        df = df.sort_values("date_posted", ascending=False, na_position="last")

    out = pathlib.Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = "".join(c if c.isalnum() else "_" for c in a.search.lower()).strip("_")
    csv_path = out / f"{slug}_{stamp}.csv"
    df.to_csv(csv_path, index=False)
    df.to_json(csv_path.with_suffix(".json"), orient="records", date_format="iso", indent=2)

    cols = [c for c in COLUMNS if c in df.columns]
    with pd.option_context("display.max_rows", 200, "display.max_colwidth", 60, "display.width", 250):
        print(df[cols].to_string(index=False))
    print(f"\n{len(df)} jobs saved to {csv_path} (+ .json)")
    print(df["site"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
