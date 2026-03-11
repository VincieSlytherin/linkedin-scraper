# LinkedIn Job Scraper with Claude AI

A Python tool that scrapes LinkedIn job listings, uses Claude AI to rank results by relevance to your resume, and delivers top matches via email. Includes a Streamlit dashboard for tracking applications and an agent mode powered by the Claude Agent SDK.

## Features

- **Resume-aware matching** — Upload your resume (PDF, DOCX, TXT, or Typst); Claude extracts your profile and uses it for scoring
- **Smart deduplication** — Jobs already sent in previous runs are automatically excluded
- **SQLite cache** — Job details and analysis results cached for 7 days; no redundant API calls
- **Adaptive rate limiting** — Automatically backs off when LinkedIn throttles requests
- **Streamlit dashboard** — Track application status, notes, and stats in a local web UI
- **Agent mode** — Conversational agent powered by Claude Agent SDK with skill-based architecture

## How It Works

```
You describe the job you want (natural language)
  → Claude generates optimized LinkedIn search parameters
  → Scraper fetches matching jobs from LinkedIn (with caching)
  → Claude analyzes & ranks each job against your resume profile
  → Deduplicates against previously sent jobs
  → Top matches emailed to your Gmail as a formatted HTML report
  → Track progress in the Streamlit dashboard
```

## Prerequisites

### 1. LinkedIn Account
- A LinkedIn account **without 2FA enabled**
- Your login email and password

### 2. Anthropic API Key
- Sign up at [console.anthropic.com](https://console.anthropic.com)
- Create an API key from the dashboard

### 3. Gmail App Password
- Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- You need **2-Step Verification** enabled on your Google account first
- Generate an App Password for "Mail"
- Copy the 16-character password

## Setup

```bash
# 1. Clone and navigate to the project
cd linkedin-job-scaper

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
cp .env.example .env
```

Edit `.env` with your credentials:

```env
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password

ANTHROPIC_API_KEY=sk-ant-your-key-here

GMAIL_ADDRESS=your_gmail@gmail.com
GMAIL_APP_PASSWORD=abcd-efgh-ijkl-mnop
GMAIL_RECIPIENT=where_to_send@gmail.com
```

## Usage

### CLI mode

```bash
python main.py
```

You'll be prompted for:
1. **Job description** — describe what you're looking for in plain English
2. **Company size** (optional) — `startup`, `small`, `medium`, `large`, `enterprise`
3. **Minimum relevance score** (optional) — 0.0–1.0, default 0.6

### Scheduled background mode (recommended)

Edit [search_config.yaml](search_config.yaml) to configure your target roles and locations:

```yaml
searches:
  titles:
    - Senior AI Engineer
    - ML Engineer
  locations:
    - San Francisco, CA
    - New York, NY

preferences:
  min_relevance_score: 0.65
  max_jobs_per_search: 15

schedule:
  interval_hours: 1
```

Then start the scheduler in the background:

```bash
# Run in foreground (Ctrl+C to stop)
python scheduler.py

# Run in background, output to logs/scheduler.log
nohup python scheduler.py &

# Run once and exit (useful for cron)
python scheduler.py --once

# macOS cron: run every hour
crontab -e
# Add:  0 * * * * cd /path/to/linkedin-job-scaper && venv/bin/python scheduler.py --once
```

The scheduler runs the full pipeline on every tick — multi-title × multi-location cross-search, deduplication, Claude analysis, and email delivery. Only jobs never previously sent are emailed. Logs are written to `logs/scheduler.log`.

### Agent mode

```bash
python agent.py
# or pass a query directly:
python agent.py "senior AI engineer roles in New York, hybrid ok"
```

The agent searches, fetches, analyzes, and presents results conversationally. It will ask before sending email.

### Streamlit dashboard

```bash
streamlit run dashboard.py
```

The dashboard has three tabs:

- **Jobs** — Browse all recommended jobs with status tracking, notes, and direct LinkedIn links
- **Resume** — Upload your resume (PDF/DOCX/TXT/Typst) so Claude scores jobs against your actual background
- **Stats** — Application funnel, score distribution, and timeline charts

Upload your resume from the **Resume** tab before running a job search — Claude will extract your profile and use it for matching.

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `LINKEDIN_EMAIL` | Yes | — | LinkedIn login email |
| `LINKEDIN_PASSWORD` | Yes | — | LinkedIn login password |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `GMAIL_ADDRESS` | Yes | — | Gmail address for sending |
| `GMAIL_APP_PASSWORD` | Yes | — | Gmail App Password (16 chars) |
| `GMAIL_RECIPIENT` | Yes | — | Where to send job results |
| `MAX_JOBS_TO_FETCH` | No | 50 | Max jobs to scrape from LinkedIn |
| `MAX_JOBS_TO_EMAIL` | No | 10 | Max top results to include in email |
| `CLAUDE_MODEL` | No | claude-sonnet-4-20250514 | Claude model for analysis |

## Project Structure

```
├── main.py              # CLI entry point — full pipeline
├── agent.py             # Claude Agent SDK conversational mode
├── dashboard.py         # Streamlit application tracking dashboard
├── config.py            # Loads and validates .env credentials
├── scraper.py           # LinkedIn auth, job search, detail fetching
├── analyzer.py          # Claude-powered search params + job analysis
├── database.py          # SQLite cache (jobs, analyses, resumes, applications)
├── emailer.py           # Formats and sends HTML email via Gmail SMTP
├── resume_parser.py     # Resume parsing (PDF, DOCX, TXT, Typst)
├── scheduler.py         # Background scheduler (runs pipeline every N hours)
├── search_config.yaml   # Scheduler config: titles, locations, preferences
├── extract_cookies.py   # Helper to extract LinkedIn browser cookies
├── skills/              # Agent skill definitions (Markdown)
│   ├── search_jobs.md
│   ├── fetch_jobs.md
│   ├── analyze_jobs.md
│   └── send_email.md
├── requirements.txt     # Python dependencies
├── .env.example         # Credential template
└── .env                 # Your credentials (not committed)
```

## Company Size Categories

| Category | Employee Count |
|---|---|
| startup | 1–50 |
| small | 51–200 |
| medium | 201–1,000 |
| large | 1,001–10,000 |
| enterprise | 10,000+ |

## Troubleshooting

**LinkedIn CHALLENGE error** (most common)

LinkedIn blocks automated logins with a CAPTCHA. Fix with cookie-based auth:

```bash
# 1. Log into linkedin.com in your browser on this machine
# 2. Run the cookie extractor
python extract_cookies.py
# 3. Paste the li_at and JSESSIONID cookie values from
#    browser DevTools → Application → Cookies → linkedin.com
# 4. Run normally — cookies are saved and reused automatically
python main.py
```

**LinkedIn authentication fails**
- Disable 2FA on your LinkedIn account
- Verify email/password in `.env`
- Try logging in via browser first if running from a new location

**Gmail send fails**
- Use an **App Password**, not your regular Gmail password
- 2-Step Verification must be enabled to generate App Passwords
- `GMAIL_ADDRESS` must match the account that owns the App Password

**Rate limiting / `KeyError: 'message'`**
- The scraper uses adaptive delays (4s base, +3s per failure, 60s cooldown after 3 consecutive failures)
- If rate-limited, wait 15–30 minutes before running again
- Cache hits (re-fetching the same jobs) are instant and don't count toward rate limits

**No jobs found**
- Try a broader or simpler keyword query
- Increase `MAX_JOBS_TO_FETCH` in `.env`

**Agent mode requires Python 3.10+ and `claude-agent-sdk`**

`claude-agent-sdk` requires Python ≥ 3.10. The rest of the project (CLI, dashboard) works on Python 3.9+.
```bash
pip install claude-agent-sdk
```
