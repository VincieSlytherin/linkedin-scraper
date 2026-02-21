# LinkedIn Job Scraper with Claude AI

A Python CLI tool that scrapes LinkedIn job listings, uses Claude AI to generate smart search queries and rank results by relevance, filters by company size, and emails the top matches to your Gmail.

## How It Works

```
You describe the job you want (natural language)
  → Claude generates optimized LinkedIn search parameters
  → Scraper fetches matching jobs from LinkedIn
  → Claude analyzes & ranks each job by relevance
  → Filters by company size preference
  → Top matches emailed to your Gmail as a formatted report
  → Summary printed to terminal
```

## Prerequisites

You'll need three sets of credentials:

### 1. LinkedIn Account
- A LinkedIn account **without 2FA enabled**
- Your login email and password

### 2. Anthropic API Key
- Sign up at [console.anthropic.com](https://console.anthropic.com)
- Create an API key from the dashboard

### 3. Gmail App Password
- Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- You need **2-Step Verification** enabled on your Google account first
- Generate an App Password (select "Mail" and your device)
- Copy the 16-character password (spaces don't matter)

> **Note:** This is NOT your regular Gmail password. App Passwords are separate credentials specifically for third-party apps.

## Setup

```bash
# 1. Clone/navigate to the project
cd linkedin-job-scraper

# 2. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

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

```bash
source venv/bin/activate
python main.py
```

You'll be prompted for:

1. **Job description** (required) — Describe what you're looking for in plain English
2. **Company size** (optional) — Filter by: `startup`, `small`, `medium`, `large`, `enterprise`
3. **Minimum relevance score** (optional) — Threshold from 0.0 to 1.0 (default: 0.6)

### Example Session

```
============================================================
  LinkedIn Job Scraper with Claude AI
============================================================

Describe the job you're looking for:
> Senior Python backend engineer in San Francisco, remote ok

Company size preferences (comma-separated, or Enter for all):
  Options: startup, small, medium, large, enterprise
> medium, large

Minimum relevance score 0.0–1.0 (Enter for 0.6):
> 0.7
```

The tool will then:
- Generate optimized search keywords using Claude
- Search LinkedIn and fetch full job details (takes a few minutes due to rate limiting)
- Analyze each job with Claude, scoring relevance and extracting pros/cons
- Email the top results to your inbox as a formatted HTML report
- Print a ranked summary to your terminal

## Configuration Options

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
| `CLAUDE_MODEL` | No | claude-sonnet-4-20250514 | Claude model to use |

## Company Size Categories

| Category | Employee Count |
|---|---|
| startup | 1–50 |
| small | 51–200 |
| medium | 201–1,000 |
| large | 1,001–10,000 |
| enterprise | 10,000+ |

## Project Structure

```
├── main.py              # CLI entry point — runs the full pipeline
├── config.py            # Loads and validates .env credentials
├── scraper.py           # LinkedIn authentication, job search, detail fetching
├── analyzer.py          # Claude-powered search query generation and job analysis
├── emailer.py           # Formats and sends HTML email via Gmail SMTP
├── extract_cookies.py   # Helper to extract LinkedIn browser cookies
├── requirements.txt     # Python dependencies
├── .env.example         # Credential template
└── .env                 # Your credentials (not committed)
```

## Troubleshooting

**LinkedIn CHALLENGE error** (most common issue)

LinkedIn blocks automated logins with a CAPTCHA challenge. Fix it with cookie-based auth:

```bash
# 1. Log into linkedin.com in your browser
# 2. Run the cookie extractor
python extract_cookies.py
# 3. It will ask you to paste two cookie values (li_at and JSESSIONID)
#    from your browser's Developer Tools → Application → Cookies
# 4. Then run the scraper normally
python main.py
```

Cookies are saved to `linkedin_cookies.json` and reused automatically on future runs.

**LinkedIn authentication fails (other)**
- Make sure 2FA is disabled on your LinkedIn account
- Check that your email/password are correct in `.env`
- LinkedIn may temporarily block logins from new locations — try logging in via browser first

**Gmail send fails**
- Ensure you're using an **App Password**, not your regular Gmail password
- 2-Step Verification must be enabled on your Google account to generate App Passwords
- Check that `GMAIL_ADDRESS` matches the account that generated the App Password

**No jobs found**
- Try a broader search query
- Increase `listed_at` (job recency) — default is 7 days
- Check if your LinkedIn account can see job listings when searching manually

**Rate limiting**
- The scraper adds a 2-second delay between LinkedIn API calls
- For 50 jobs, expect ~2–3 minutes for the fetching phase
- If you hit rate limits, wait 15–30 minutes before running again
