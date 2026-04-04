# Free-Agent 

An automated internship tracking bot that monitors the two most-watched SWE internship repositories on GitHub and delivers batched email alerts for new postings — so you hear about roles the moment they drop, not hours later.

Built with Python and GitHub Actions. Zero infrastructure, zero cost.

---

## What it does

Every 30 minutes, a GitHub Actions runner spins up, fetches the latest data from both repositories, identifies anything new, and sends a single batched email containing only unseen opportunities. If nothing has changed, it exits silently — no noise.

**Repositories monitored:**
- [speedyapply/2026-SWE-College-Jobs](https://github.com/speedyapply/2026-SWE-College-Jobs)
- [SimplifyJobs/Summer2026-Internships](https://github.com/SimplifyJobs/Summer2026-Internships)

---

## Architecture

The bot runs as a single Python script across six phases:

**1. Fetch** — Pulls the raw README from both repos using authenticated GitHub API requests (5,000 req/hr limit vs 60 unauthenticated).

**2. Parse** — Detects the table format of each repo and routes to the appropriate parser. SpeedyApply uses standard markdown pipe tables; Simplify embeds HTML tables directly in the markdown. Both parsers implement the same `↳` state machine: when a row's company column contains an arrow, the script injects the last seen company name so nested roles are correctly attributed.

**3. Hash** — For each parsed job, the script normalizes `company + role + location` (lowercase, strip punctuation, collapse whitespace) and generates a SHA-256 fingerprint. Normalization ensures "New York, NY" and "New York, NY " don't produce two different hashes for the same role.

**4. Deduplicate** — Compares every hash against a single global `seen_jobs.json`. If a job appears on SpeedyApply first and Simplify later, it gets caught on the first run and ignored on the second. One JSON file, one source of truth, across both repos.

**5. Notify** — If new leads exist, assembles a single batched HTML email grouped by source and sends it via the Resend API. One email per run, never one per job.

**6. Persist** — Commits the updated hash set to a separate `data` branch, keeping `main` clean. The `data` branch acts as a lightweight database — no external services required.

```
main branch          data branch
├── scraper.py       └── seen_jobs.json   ← hash memory
├── requirements.txt
└── .github/
    └── workflows/
        └── tracker.yml
```

---

## Tech stack

- **Python 3.11** — requests, resend, html.parser (stdlib)
- **GitHub Actions** — cron scheduler, secrets management, runner environment
- **Resend API** — transactional email delivery
- **SHA-256** — job deduplication fingerprinting
- **Git** — used as a database via branch strategy

---

## How to run your own instance

**1. Fork this repo**

**2. Create the data branch**
```bash
git checkout --orphan data
git rm -rf .
echo '[]' > seen_jobs.json
git add seen_jobs.json
git commit -m "init: create data branch"
git push origin data
git checkout main
```

**3. Set up Resend**

Create a free account at [resend.com](https://resend.com). The free tier allows 3,000 emails/month. Use `onboarding@resend.dev` as your sender address for testing — no domain required.

**4. Add GitHub secrets**

Go to your repo → Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `RESEND_API_KEY` | Your Resend API key |
| `EMAIL_FROM` | Your verified Resend sender address |
| `EMAIL_TO` | Where you want alerts delivered |

`GITHUB_TOKEN` is injected automatically by Actions — no setup needed.

**5. Trigger a manual run**

Go to Actions → Internship Tracker → Run workflow.

The first run will email every currently listed role as a one-time catch-up. Every subsequent run only emails new additions.

---

## Edge cases handled

| Scenario | Solution |
|---|---|
| Nested roles (`↳`) | State machine tracks `current_company`, injects it into arrow rows |
| Closed roles (🔒) | Silently dropped before hashing |
| HTML vs markdown tables | Format detected at runtime, routed to appropriate parser |
| Malformed rows | Per-row `try/except` — one bad row doesn't crash the run |
| One repo down | Processes the other, sends partial email |
| Email failure | Logs loudly, still persists updated hashes |
| Duplicate across repos | Single hash store catches cross-repo duplicates |
| Location string variance | Normalized before hashing — "NYC" and "NYC " hash identically |

---

## Cost

**Free.** GitHub Actions free tier includes 2,000 minutes/month. This bot uses roughly 50–100 minutes/month at 30-minute intervals.
