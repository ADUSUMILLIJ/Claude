#!/usr/bin/env python3
"""Fresh, resume-matched job search across Indeed + Greenhouse/Lever/Ashby/Workday.

Pipeline (all settings in config/profile.json):
  1. Indeed (via JobSpy) for each search term, last N hours, US.
  2. Greenhouse / Lever / Ashby public job-board APIs for every slug in data/ats_slugs.txt.
  3. Keep only postings hosted on Indeed or applying through Greenhouse/Lever/Workday/Ashby.
  4. Filters: US, full-time/contract, professional supply-chain roles (no clerk/warehouse/
     driver/handler/supervisor/manager), experience <= max years, OPT-safe (no ITAR / citizenship /
     clearance / no-sponsorship wording), STEM evidence (SQL/ERP/MRP/forecasting/BI...).
  5. Repost / freshness check against the ATS itself (Workday startDate, Greenhouse
     first_published, Lever createdAt, Ashby publishedAt); keeps only postings dated today.
  6. Resolves direct ATS URLs, scores against resume skills, flags E-Verify mentions.
  7. Drops anything already listed in data/seen_jobs.csv, then appends the new ones to it.

Usage:
  python3 scripts/job_search.py                 # default supply-chain search
  python3 scripts/job_search.py --terms "demand planner" "buyer"
  python3 scripts/job_search.py --include-seen  # don't hide previously shown jobs
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import sys
import time
import warnings

warnings.filterwarnings("ignore", message="This pattern is interpreted as a regular expression")
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROFILE = ROOT / "config" / "profile.json"
SLUGS = ROOT / "data" / "ats_slugs.txt"
SEEN = ROOT / "data" / "seen_jobs.csv"
OUTDIR = ROOT / "jobs"

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0"

# ---------------------------------------------------------------- patterns
REL = re.compile(r"supply chain|procure|purchas|buyer|sourcing|planner|planning|inventory|demand|supply|"
                 r"logistic|material|import|export|customs|supplier|vendor|replenish|allocation|s&op|"
                 r"commodit|category|fulfil|distribution|transportation|freight|scheduler|"
                 r"production control|expedit|operations analyst|scm\b", re.I)
FIT = re.compile(r"analyst|planner|planning|buyer|purchasing agent|procurement|sourcing|"
                 r"supply chain (coordinator|specialist|analyst|associate|engineer)|"
                 r"inventory (analyst|control|specialist|coordinator)|logistics (coordinator|specialist|analyst)|"
                 r"materials? (coordinator|planner|control)|import|export|customs|demand|supply|scheduler|"
                 r"production control|integrator|rotational|fulfillment analyst|freight operations coordinator|"
                 r"purchasing|category (analyst|specialist)|supplier quality engineer|program specialist", re.I)
BAD = re.compile(r"clerk|warehouse (associate|worker|agent|lead|team|selector|operator|i\b|utility|material)|"
                 r"driver|forklift|handler|picker|selector|operator|cdl|dock|receiving|shipping (associate|&)|"
                 r"technician|\btech\b|trainer|supervisor|manager|director|\blead\b|senior|\bsr\.?\b|\bhead\b|"
                 r"\bvp\b|principal|instructor|talent acquisition|recruiter|conference|counter sales|cycle counter|"
                 r"stock associate|packing|courier|delivery|team member|helper|loader|sales|merchandise|"
                 r"account (manager|executive)|business development|broker|google ads|security|event|"
                 r"financial planning|paraplanner|retirement|wealth|intern\b|internship|part[- ]time|"
                 r"night shift|administrator vi", re.I)
STEM = re.compile(r"\bsql\b|\bsap\b|\berp\b|oracle|power ?bi|tableau|data analy\w*|analytics|database|python|"
                  r"\bmrp\b|statistic\w*|dashboards?|excel (?:model\w*|macros?|vba)|advanced excel|pivot tables?|"
                  r"vlookup|\bvba\b|\bkpis?\b|information systems?|netsuite|dynamics 365|\bwms\b|\btms\b|forecast\w*", re.I)
RESTRICT = [r"(?i)(not|unable to|cannot|won't|will not|do not|does not)\s+(be able to\s+)?(provide|offer|sponsor|support)"
            r"[^.]{0,40}(sponsor|visa|work authori)",
            r"(?i)without (the need for|requiring)[^.]{0,30}sponsorship", r"(?i)no (visa )?sponsorship",
            r"(?i)must be a U\.?S\.? citizen|U\.?S\.? citizenship (is )?required|requires? U\.?S\.? citizenship",
            r"(?i)U\.?S\.? person", r"\bITAR\b", r"\bEAR\b|(?i:export administration regulations)",
            r"(?i)security clearance", r"(?i)green card"]
US = re.compile(r"united states|\bUSA?\b|remote|, (A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|"
                r"N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b", re.I)
NONUS = re.compile(r"canada|mexico|\buk\b|london|india|germany|ireland|netherlands|poland|philippines|"
                   r"singapore|china|japan|australia", re.I)
NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
WORDS = dict(one=1, two=2, three=3, four=4, five=5, six=6, seven=7, eight=8, nine=9, ten=10)
EXP = re.compile(NUM + r"\s*\+?\s*(?:(?:-|–|to|or)\s*" + NUM + r"\s*\+?\s*)?(?:\(\d+\)\s*)?(?:years?|yrs?)", re.I)


def min_exp(text: str):
    text = text or ""
    vals = []
    for m in EXP.finditer(text):
        ctx = text[m.end():m.end() + 120].lower()
        if "exp" not in text[max(0, m.start() - 80):m.end() + 120].lower():
            continue
        if re.search(r"degree|bachelor|master|age|old|warranty|company|history|founded|in business|serving", ctx[:40]):
            continue
        v = m.group(1).lower()
        v = int(WORDS.get(v, v))
        if v <= 20:
            vals.append(v)
    return min(vals) if vals else None


def restriction(text: str):
    for pat in RESTRICT:
        m = re.search(pat, text or "")
        if m:
            return m.group(0)
    return None


def ats_of(url) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    h = urlparse(url).netloc.lower()
    if "myworkdayjobs" in h or "myworkdaysite" in h:
        return "Workday"
    if "greenhouse.io" in h or h == "grnh.se":
        return "Greenhouse"
    if "lever.co" in h:
        return "Lever"
    if "ashbyhq" in h:
        return "Ashby"
    return None


def curl_json(url: str, tries: int = 5):
    """Workday rate-limits python clients; curl with backoff is reliable."""
    for t in range(tries):
        r = subprocess.run(["curl", "-s", "-m", "25", "-A", "Mozilla/5.0", "-H", "Accept: application/json",
                            "-w", "\n%{http_code}", url], capture_output=True, text=True).stdout
        body, _, code = r.rpartition("\n")
        if code == "429":
            time.sleep(4 * (t + 1))
            continue
        try:
            return json.loads(body)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------- sources
def fetch_indeed(terms, prof):
    from jobspy import scrape_jobs
    dfs = []
    for t in terms:
        try:
            df = scrape_jobs(site_name=["indeed"], search_term=t, location=prof["location"], results_wanted=300,
                             hours_old=prof["hours"], country_indeed=prof["country"], verbose=0)
            print(f"  indeed '{t}': {len(df)}", flush=True)
            dfs.append(df)
        except Exception as e:
            print(f"  indeed '{t}': ERROR {e}", flush=True)
    if not dfs:
        return []
    d = pd.concat(dfs).drop_duplicates("job_url")
    rows = []
    for _, r in d.iterrows():
        direct = r.job_url_direct if isinstance(r.job_url_direct, str) else None
        ats = "Indeed" if direct is None else ats_of(direct)
        if not ats:
            continue
        jt = r.job_type if isinstance(r.job_type, str) else ""
        rows.append(dict(ats=ats, company=r.company, title=r.title, location=str(r.location), job_type=jt,
                         posted=str(r.date_posted), url=direct or r.job_url, indeed_url=r.job_url,
                         desc=r.description or "",
                         salary=(f"${r.min_amount:,.0f}-${r.max_amount:,.0f}/{r.interval}"
                                 if pd.notna(r.min_amount) and pd.notna(r.max_amount) else "")))
    return rows


def _gh(slug):
    r = S.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=20)
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        out.append(dict(ats="Greenhouse", company=j.get("company_name") or slug, title=j["title"],
                        location=j["location"]["name"], job_type="", posted=j.get("first_published") or j["updated_at"],
                        url=j["absolute_url"], desc=re.sub("<[^>]+>", " ", html.unescape(j.get("content", ""))), salary=""))
    return out


def _lv(slug):
    r = S.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=20)
    if r.status_code != 200 or not isinstance(r.json(), list):
        return []
    out = []
    for j in r.json():
        c = dt.datetime.fromtimestamp(j["createdAt"] / 1000, dt.timezone.utc)
        cat = j.get("categories", {})
        out.append(dict(ats="Lever", company=slug, title=j["text"], location=cat.get("location") or "",
                        job_type=cat.get("commitment") or "", posted=c.isoformat(), url=j["hostedUrl"],
                        desc=j.get("descriptionPlain", "") + " " + j.get("additionalPlain", ""), salary=""))
    return out


def _ab(slug):
    r = S.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true", timeout=20)
    if r.status_code != 200:
        return []
    out = []
    for j in r.json().get("jobs", []):
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry") or ""
        out.append(dict(ats="Ashby", company=slug, title=j["title"], location=f"{j.get('location') or ''} {country}",
                        job_type=j.get("employmentType") or "", posted=j.get("publishedAt"), url=j.get("jobUrl"),
                        desc=j.get("descriptionPlain", ""), salary=""))
    return out


def fetch_boards(slugs):
    def one(s):
        res = []
        for f in (_gh, _lv, _ab):
            try:
                res += [x for x in f(s) if REL.search(x["title"])]
            except Exception:
                pass
        return res
    rows = []
    with cf.ThreadPoolExecutor(24) as ex:
        for r in ex.map(one, slugs):
            rows += r
    return rows


# ---------------------------------------------------------------- verification / direct URLs
def verify(row, tz):
    """Return (original_post_date_local: date|None, direct_url)."""
    u, ats = row["url"], row["ats"]
    if ats == "Indeed":
        return dt.date.fromisoformat(row["posted"][:10]), row.get("indeed_url") or u
    if ats == "Workday":
        p = urlparse(u)
        parts = [x for x in p.path.split("/") if x]
        if parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
            parts = parts[1:]
        if "myworkdaysite" in p.netloc and parts and parts[0] == "recruiting":  # /recruiting/<tenant>/<site>/job/...
            tenant, parts = parts[1], parts[2:]
            api = f"https://{p.netloc}/wday/cxs/{tenant}/{parts[0]}/{'/'.join(parts[1:])}"
            direct = u
        else:
            tenant = p.netloc.split(".")[0]
            api = f"https://{p.netloc}/wday/cxs/{tenant}/{parts[0]}/{'/'.join(parts[1:])}"
            direct = f"https://{p.netloc}/en-US/{parts[0]}/{'/'.join(parts[1:])}"
        j = curl_json(api)
        time.sleep(0.6)
        try:
            return dt.date.fromisoformat(j["jobPostingInfo"]["startDate"][:10]), direct
        except Exception:
            return None, direct
    if ats == "Greenhouse":
        final = u
        if urlparse(u).netloc == "grnh.se":
            try:
                final = S.get(u, timeout=20, allow_redirects=True).url
            except Exception:
                pass
        m = re.search(r"greenhouse\.io/([\w-]+)/jobs/(\d+)", final)
        jid = (parse_qs(urlparse(final).query).get("gh_jid") or [None])[0]
        slug = m.group(1) if m else None
        jid = m.group(2) if m else jid
        if jid and not slug:
            host = urlparse(final).netloc.replace("www.", "").split(".")[0]
            q = parse_qs(urlparse(final).query)
            comp = re.sub(r"\W", "", str(row["company"]).lower())
            for s in dict.fromkeys((q.get("board") or []) + [host, comp, host + "com", host + "inc"]):
                if S.get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs/{jid}", timeout=15).status_code == 200:
                    slug = s
                    break
        if slug and jid:
            try:
                j = S.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}", timeout=20).json()
                fp = j.get("first_published") or j.get("updated_at")
                return (pd.Timestamp(fp).tz_convert(tz).date() if fp else None,
                        f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}")
            except Exception:
                return None, f"https://job-boards.greenhouse.io/{slug}/jobs/{jid}"
        return None, final
    if ats == "Lever":
        parts = [x for x in urlparse(u).path.split("/") if x]
        clean = f"https://jobs.lever.co/{parts[0]}/{parts[1]}"
        try:
            j = S.get(f"https://api.lever.co/v0/postings/{parts[0]}/{parts[1]}", timeout=20).json()
            return dt.datetime.fromtimestamp(j["createdAt"] / 1000, tz).date(), clean
        except Exception:
            return None, clean
    if ats == "Ashby":
        parts = [x for x in urlparse(u).path.split("/") if x]
        clean = f"https://jobs.ashbyhq.com/{parts[0]}/{parts[1]}"
        try:
            for j in S.get(f"https://api.ashbyhq.com/posting-api/job-board/{parts[0]}", timeout=20).json()["jobs"]:
                if parts[1] in (j.get("jobUrl") or ""):
                    return pd.Timestamp(j["publishedAt"]).tz_convert(tz).date(), clean
        except Exception:
            pass
        return None, clean
    return None, u


# ---------------------------------------------------------------- seen-jobs memory
def norm_key(company, title, location):
    f = lambda s: re.sub(r"\W", "", str(s).lower())
    return f"{f(company)}|{f(title)}|{f(str(location).replace(', USA', ''))}"


def load_seen():
    if not SEEN.exists():
        return set(), set()
    s = pd.read_csv(SEEN)
    return set(s.url.dropna()), set(s.key.dropna())


def save_seen(df):
    new = pd.DataFrame({"first_shown": dt.date.today().isoformat(), "url": df["Direct URL"],
                        "key": [norm_key(c, t, l) for c, t, l in zip(df.Company, df.Title, df.Location)],
                        "title": df.Title, "company": df.Company})
    if SEEN.exists():
        new = pd.concat([pd.read_csv(SEEN), new]).drop_duplicates("url")
    SEEN.parent.mkdir(exist_ok=True)
    new.to_csv(SEEN, index=False)


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--terms", nargs="+", help="Override Indeed search terms")
    ap.add_argument("--include-seen", action="store_true", help="Also show jobs given in earlier runs")
    ap.add_argument("--no-today-only", action="store_true", help="Keep anything within --hours, not just today")
    ap.add_argument("--no-stem", action="store_true", help="Skip the STEM-evidence filter")
    ap.add_argument("--no-boards", action="store_true", help="Skip direct Greenhouse/Lever/Ashby board scan")
    a = ap.parse_args()
    prof = json.loads(PROFILE.read_text())
    tz = ZoneInfo(prof.get("timezone", "America/New_York"))
    today = dt.datetime.now(tz).date()

    print("1/5 Fetching Indeed ...", flush=True)
    rows = fetch_indeed(a.terms or prof["indeed_search_terms"], prof)
    if not a.no_boards:
        print("2/5 Scanning ATS boards ...", flush=True)
        slugs = SLUGS.read_text().split()
        rows += fetch_boards(slugs)
    df = pd.DataFrame(rows)
    if df.empty:
        print("No postings returned.")
        return 1
    print(f"   pool: {len(df)}  {df.ats.value_counts().to_dict()}", flush=True)

    print("3/5 Filtering ...", flush=True)
    df = df[df.ats.isin(prof["sites"])]
    df = df[df.location.str.contains(US) & ~(df.location.str.contains(NONUS) & ~df.location.str.contains("United States|USA"))]
    jt = df.job_type.fillna("").str.lower()
    df = df[~jt.str.contains("part") | jt.str.contains("full")]
    df = df[~jt.str.contains("intern")]
    df = df[df.title.str.contains(REL) & df.title.str.contains(FIT) & ~df.title.str.contains(BAD)]
    df = df[~df.desc.str.contains(r"\brepost", case=False)]
    df["min_years"] = df.desc.map(min_exp)
    df = df[df.min_years.isna() | (df.min_years <= prof["max_experience_years"])]
    if prof.get("opt_stem", True):
        df["restricts"] = df.desc.map(restriction)
        df = df[df.restricts.isna()]
    df["stem_hits"] = [sorted({m.lower() for m in STEM.findall(t + " " + d)}) for t, d in zip(df.title, df.desc)]
    if prof.get("opt_stem", True) and not a.no_stem:
        df = df[df.stem_hits.map(len) >= prof.get("min_stem_evidence", 2)]
    df["key"] = [norm_key(c, t, l) for c, t, l in zip(df.company, df.title, df.location)]
    df = df.sort_values("ats", key=lambda s: s.eq("Indeed")).drop_duplicates("key")

    seen_urls, seen_keys = (set(), set()) if a.include_seen else load_seen()
    df = df[~df.key.isin(seen_keys)]
    print(f"   candidates after filters (not seen before): {len(df)}", flush=True)

    print("4/5 Verifying post dates on the ATS + resolving direct links ...", flush=True)
    res = [verify(r, tz) for r in df.to_dict("records")]
    df["orig_date"] = [x[0] for x in res]
    df["Direct URL"] = [x[1] for x in res]
    df = df[~df["Direct URL"].isin(seen_urls)]
    if prof.get("today_only", True) and not a.no_today_only:
        df = df[df.orig_date == today]
    else:
        df = df[df.orig_date.isna() | (df.orig_date >= today - dt.timedelta(days=max(1, prof["hours"] // 24)))]

    print("5/5 Scoring against resume ...", flush=True)
    skills = prof["resume_skills"]
    def score(r):
        t = (r.title + " " + r.desc).lower()
        s = sum(1 for x in skills if x in t)
        s += 6 if re.search(r"analyst|planner|planning|integrator|rotational", r.title, re.I) else 0
        s += 4 if re.search(r"supply chain|inventory|demand|procure|buyer|purchas", r.title, re.I) else 0
        return s
    df["Match"] = df.apply(score, axis=1) if len(df) else []
    df["Fit"] = pd.cut(df.Match, [-1, 9, 15, 999], labels=["Fair", "Good", "Strong"]) if len(df) else []
    df["E-Verify"] = df.desc.str.contains(r"e-?\s?verify", case=False).map({True: "Stated in posting", False: "Verify"})
    out = df.rename(columns={"title": "Title", "company": "Company", "location": "Location", "job_type": "Job Type",
                             "ats": "Site", "salary": "Salary", "orig_date": "Posted"})
    out["Min Exp (yrs)"] = out.min_years.map(lambda x: "Not stated" if pd.isna(x) else int(x))
    out["STEM evidence"] = out.stem_hits.map(lambda x: ", ".join(x[:8]))
    out["Location"] = out.Location.str.replace(", USA", "")
    out = out.sort_values("Match", ascending=False)[["Fit", "Match", "Title", "Company", "Location", "Job Type", "Site",
                                                     "Min Exp (yrs)", "E-Verify", "STEM evidence", "Salary", "Posted",
                                                     "Direct URL"]]
    OUTDIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now(tz).strftime("%Y-%m-%d_%H%M")
    path = OUTDIR / f"fresh_jobs_{stamp}"
    out.to_csv(f"{path}.csv", index=False)
    out.to_excel(f"{path}.xlsx", index=False)
    if not a.include_seen and len(out):
        save_seen(out)

    print(f"\n{len(out)} NEW jobs  ->  {path}.xlsx")
    for _, r in out.iterrows():
        print(f"[{r.Fit}] {r.Title} — {r.Company} ({r.Location}) | {r.Site} | exp {r['Min Exp (yrs)']} | E-Verify: {r['E-Verify']}")
        print(f"    {r['Direct URL']}")
    print("\nURLS")
    print("\n".join(out["Direct URL"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
