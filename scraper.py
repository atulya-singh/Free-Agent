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

resend.api_key     = os.environ["RESEND_API_KEY"]
EMAIL_FROM         = os.environ["EMAIL_FROM"]
EMAIL_TO           = os.environ["EMAIL_TO"]
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")

