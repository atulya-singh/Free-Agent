import hashlib
import json
import os
import re 
import subprocess
import sys
from datetime import datetime

import requests
import resend

# CONFIG

REPOS = [
    {
        "label": "SpeedApply 2026", 
        "raw_url": "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/README.md",
    },
    {
        "label": "Simplify Summer 2026",
        "raw_url": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
    },
]

SEEN_JOBS_FILE = "seen_jobs.json"

RESEND_API_KEY = os.environ["RESEND_API_KEY"]
resend.api_key = RESEND_API_KEY
EMAIL_FROM     = os.environ["EMAIL_FROM"]
EMAIL_TO       = os.environ["EMAIL_TO"]
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

