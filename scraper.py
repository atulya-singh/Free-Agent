import hashlib
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from html.parser import HTMLParser

import requests
import resend

# CONFIG

REPOS = [
    {
        "label": "SpeedyApply 2026",
        "raw_url": "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/README.md",
    },
    {
        "label": "Simplify Summer 2026",
        "raw_url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
    },
]

SEEN_JOBS_FILE = "seen_jobs.json"

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
resend.api_key = RESEND_API_KEY
EMAIL_FROM     = os.environ.get("EMAIL_FROM", "")
EMAIL_TO       = os.environ.get("EMAIL_TO", "")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")


# ---------------------------------------------------------------------------
# Section 1: Logger
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Section 2: Fetcher
# ---------------------------------------------------------------------------

def fetch_readme(repo: dict) -> str | None:
    url = repo["raw_url"]
    label = repo["label"]
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        log(f"Fetched {label} ({len(resp.text)} chars)")
        return resp.text
    except requests.RequestException as e:
        log(f"Failed to fetch {label}: {e}")
        return None


# ---------------------------------------------------------------------------
# Section 3: Parser
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text).strip()


def _parse_markdown_table(lines: list[str], label: str) -> list[dict]:
    """Parse markdown pipe-table format (used by SpeedyApply)."""
    jobs: list[dict] = []
    current_company = ""
    total_rows = 0

    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        if "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]

        if len(cells) < 3:
            continue

        if any(h.lower() in ("company", "name") for h in cells):
            continue

        total_rows += 1

        try:
            if "🔒" in line:
                continue

            cells_clean = [_strip_html(c) for c in cells]

            raw_company = cells_clean[0] if len(cells_clean) > 0 else ""

            if raw_company and raw_company != "↳":
                current_company = raw_company

            company = current_company
            role = cells_clean[1] if len(cells_clean) > 1 else ""
            location = cells_clean[2] if len(cells_clean) > 2 else ""

            url = ""
            for cell_text in line.split("|"):
                m = _MD_LINK_RE.search(cell_text)
                if m:
                    url = m.group(2)
                    break

            m_company = _MD_LINK_RE.search(company)
            if m_company:
                company = m_company.group(1)

            m_role = _MD_LINK_RE.search(role)
            if m_role:
                url = url or m_role.group(2)
                role = m_role.group(1)

            company = _strip_html(company)
            role = _strip_html(role)
            location = _strip_html(location)

            if not company or not role:
                continue

            jobs.append({
                "company": company,
                "role": role,
                "location": location,
                "url": url,
                "source": label,
            })
        except Exception as e:
            log(f"Skipping bad row in {label}: {e}")
            continue

    log(f"{label}: {len(jobs)} valid jobs parsed from {total_rows} markdown table rows")
    return jobs


class _TableParser(HTMLParser):
    """HTMLParser subclass that extracts rows from HTML tables."""

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []      # {"cells": [...], "hrefs": [...], "raw": str}
        self._in_tr = False
        self._in_td = False
        self._in_th = False
        self._current_cells: list[str] = []
        self._current_hrefs: list[str] = []
        self._current_text = ""
        self._current_raw = ""
        self._is_header_row = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._in_tr = True
            self._current_cells = []
            self._current_hrefs = []
            self._current_raw = ""
            self._is_header_row = False
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._current_text = ""
        elif tag == "th" and self._in_tr:
            self._in_th = True
            self._is_header_row = True
        elif tag == "a" and self._in_tr:
            for name, value in attrs:
                if name == "href" and value:
                    self._current_hrefs.append(value)
        if self._in_tr:
            self._current_raw += self.get_starttag_text() or ""

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._in_td:
            self._current_cells.append(self._current_text.strip())
            self._in_td = False
        elif tag == "th":
            self._in_th = False
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if not self._is_header_row and self._current_cells:
                self.rows.append({
                    "cells": self._current_cells,
                    "hrefs": self._current_hrefs,
                    "raw": self._current_raw,
                })
        if self._in_tr:
            self._current_raw += f"</{tag}>"

    def handle_data(self, data: str) -> None:
        if self._in_td:
            self._current_text += data
        if self._in_tr:
            self._current_raw += data

    def handle_entityref(self, name: str) -> None:
        char = html.unescape(f"&{name};")
        if self._in_td:
            self._current_text += char
        if self._in_tr:
            self._current_raw += char

    def handle_charref(self, name: str) -> None:
        char = html.unescape(f"&#{name};")
        if self._in_td:
            self._current_text += char
        if self._in_tr:
            self._current_raw += char


def _parse_html_table(markdown: str, label: str) -> list[dict]:
    """Parse HTML <table> format (used by Simplify)."""
    parser = _TableParser()
    parser.feed(markdown)

    jobs: list[dict] = []
    current_company = ""
    total_rows = 0

    for row in parser.rows:
        cells = row["cells"]
        hrefs = row["hrefs"]
        raw = row["raw"]

        if len(cells) < 3:
            continue

        # Skip header rows
        if any(c.lower() in ("company", "role") for c in cells):
            continue

        total_rows += 1

        try:
            if "🔒" in raw:
                continue

            # Extract URL — prefer non-Simplify links (direct company links)
            url = ""
            for href in hrefs:
                if "simplify.jobs" not in href:
                    url = href
                    break
            if not url and hrefs:
                url = hrefs[0]

            # Column layout: Company | Role | Location | Application | Age
            raw_company = html.unescape(cells[0]).strip()
            role = html.unescape(cells[1]).strip()
            location = html.unescape(cells[2]).strip()

            if raw_company and raw_company != "↳":
                current_company = raw_company

            company = current_company

            if not company or not role:
                continue

            jobs.append({
                "company": company,
                "role": role,
                "location": location,
                "url": url,
                "source": label,
            })
        except Exception as e:
            log(f"Skipping bad row in {label}: {e}")
            continue

    log(f"{label}: {len(jobs)} valid jobs parsed from {total_rows} HTML table rows")
    return jobs


def parse_jobs(markdown: str, label: str) -> list[dict]:
    lines = markdown.splitlines()
    if markdown.count("<tr") > markdown.count("|"):
        log(f"{label}: detected HTML table format")
        return _parse_html_table(markdown, label)
    else:
        log(f"{label}: detected markdown table format")
        return _parse_markdown_table(lines, label)


# ---------------------------------------------------------------------------
# Section 4: Hasher
# ---------------------------------------------------------------------------

_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


def make_hash(job: dict) -> str:
    raw = f"{job['company']}{job['role']}{job['location']}"
    normalized = _PUNCTUATION_RE.sub("", raw.lower().strip())
    normalized = " ".join(normalized.split())  # collapse whitespace
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Section 5: Deduplicator
# ---------------------------------------------------------------------------

def load_seen(filepath: str) -> set[str]:
    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def filter_new(jobs: list[dict], seen: set[str]) -> list[dict]:
    return [job for job in jobs if make_hash(job) not in seen]


def merge_seen(seen: set[str], new_jobs: list[dict]) -> set[str]:
    updated = set(seen)
    for job in new_jobs:
        updated.add(make_hash(job))
    return updated


# ---------------------------------------------------------------------------
# Section 6: Email Builder
# ---------------------------------------------------------------------------

def build_email(new_leads: list[dict]) -> tuple[str, str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"{len(new_leads)} New Job Leads — {now}"

    # Group by source
    grouped: dict[str, list[dict]] = {}
    for job in new_leads:
        grouped.setdefault(job["source"], []).append(job)

    html_parts = [
        "<html><body>",
        f"<h2>{len(new_leads)} New Job Leads</h2>",
        f"<p>Scraped at {now}</p>",
    ]

    for source, jobs in grouped.items():
        html_parts.append(f"<h3>{source}</h3>")
        html_parts.append(
            "<table border='1' cellpadding='6' cellspacing='0' "
            "style='border-collapse:collapse;'>"
        )
        html_parts.append(
            "<tr><th>Company</th><th>Role</th>"
            "<th>Location</th><th>Apply</th></tr>"
        )
        for job in jobs:
            link = (
                f"<a href='{job['url']}'>Apply</a>" if job["url"] else "N/A"
            )
            html_parts.append(
                f"<tr><td>{job['company']}</td><td>{job['role']}</td>"
                f"<td>{job['location']}</td><td>{link}</td></tr>"
            )
        html_parts.append("</table>")

    html_parts.append("</body></html>")
    return subject, "\n".join(html_parts)


# ---------------------------------------------------------------------------
# Section 7: Emailer
# ---------------------------------------------------------------------------

def send_email(html: str, subject: str) -> bool:
    try:
        params = {
            "from": EMAIL_FROM,
            "to": [EMAIL_TO],
            "subject": subject,
            "html": html,
        }
        resp = resend.Emails.send(params)
        try:
            email_id = resp["id"]
        except (KeyError, TypeError):
            email_id = "unknown"
        log(f"Email sent successfully (id={email_id})")
        return True
    except Exception as e:
        log(f"Email send failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Section 8: Persister
# ---------------------------------------------------------------------------

def save_seen(seen: set[str], filepath: str) -> None:
    with open(filepath, "w") as f:
        json.dump(sorted(seen), f, indent=2)
    log(f"Saved {len(seen)} hashes to {filepath}")


def push_to_data_branch(filepath: str) -> None:
    import shutil

    def _run(cmd: list[str], description: str) -> bool:
        try:
            subprocess.run(
                cmd, capture_output=True, text=True, check=True
            )
            log(f"git: {description} — OK")
            return True
        except subprocess.CalledProcessError as e:
            log(f"git: {description} — FAILED: {e.stderr.strip()}")
            return False

    _run(["git", "config", "user.email", "bot@free-agent.dev"], "set email")
    _run(["git", "config", "user.name", "Free-Agent Bot"], "set name")

    if not _run(["git", "fetch", "origin", "data"], "fetch data branch"):
        log("Could not fetch data branch — aborting push")
        return

    # Save a copy of the file before switching branches
    tmp_path = "/tmp/seen_jobs.json"
    shutil.copy2(filepath, tmp_path)

    if not _run(["git", "checkout", "data"], "checkout data"):
        log("Could not checkout data branch — aborting push")
        return

    # Copy updated file into place
    shutil.copy2(tmp_path, filepath)

    _run(["git", "add", filepath], "stage seen_jobs.json")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not _run(
        ["git", "commit", "-m", f"chore: update seen_jobs [{timestamp}]"],
        "commit",
    ):
        log("Nothing to commit or commit failed")

    if not _run(["git", "push", "origin", "data"], "push data"):
        log("Push to data branch failed!")

    # Switch back to original branch
    _run(["git", "checkout", "-"], "return to previous branch")


# ---------------------------------------------------------------------------
# Section 9: main()
# ---------------------------------------------------------------------------

def main() -> None:
    import time

    start = time.time()
    log("Starting scraper run")

    # 1. Fetch both READMEs
    all_jobs: list[dict] = []
    for repo in REPOS:
        markdown = fetch_readme(repo)
        if markdown is None:
            continue
        # 2. Parse into jobs
        jobs = parse_jobs(markdown, repo["label"])
        all_jobs.extend(jobs)

    log(f"Total jobs across all sources: {len(all_jobs)}")

    # 3. Load seen hashes
    seen = load_seen(SEEN_JOBS_FILE)
    log(f"Loaded {len(seen)} previously seen hashes")

    # 4. Filter to new leads
    new_leads = filter_new(all_jobs, seen)
    log(f"New leads: {len(new_leads)}")

    # 5. Exit early if nothing new
    if not new_leads:
        log("No new jobs found — exiting")
        sys.exit(0)

    # 6. Build and send email
    subject, html = build_email(new_leads)
    send_email(html, subject)

    # 7. Merge and save seen hashes
    seen = merge_seen(seen, new_leads)
    save_seen(seen, SEEN_JOBS_FILE)

    # 8. Push to data branch
    push_to_data_branch(SEEN_JOBS_FILE)

    # 9. Log runtime
    elapsed = time.time() - start
    log(f"Done in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
