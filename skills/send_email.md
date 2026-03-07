# Send Email Skill

Send the top-ranked job results to the user's configured email address.

## Tool: `send_email`

**Purpose**: Deliver a formatted HTML email with the top job results to the recipient configured in `.env` (`GMAIL_RECIPIENT`). Marks jobs as "sent" in the database so they are excluded from future runs.

**Parameters**:
- `search_query` (string, required): The search query string used as the email subject/header.
- `max_jobs` (integer, optional): Maximum number of jobs to include in the email. Default: 10 (from config `MAX_JOBS_TO_EMAIL`).

**Returns**: JSON with:
- `success` (bool): Whether the email was sent successfully
- `sent_to`: recipient email address
- `jobs_sent`: number of jobs included
- `job_ids`: list of job IDs marked as sent

## Guidelines

- Only call `send_email` after `analyze_jobs` has been run.
- Only send jobs with `strong_match` or `good_match` recommendations — do not send `weak_match` or `no_match` jobs.
- Ask the user for confirmation before sending if the results are unclear or the user hasn't explicitly requested delivery.
- The email includes: job title, company, location, score, skills match/gap, pros/cons, and a direct LinkedIn link.
- Jobs included in the email are permanently recorded as "sent" and will not appear in future recommendation runs.
- If `success` is false, do not retry automatically — ask the user to check Gmail credentials.

## When to Send

Send immediately (without extra confirmation) when:
- The user explicitly says "send", "email me", "recommend", or similar
- There are clear `strong_match` / `good_match` results available

Ask for confirmation before sending when:
- Results are borderline (all `weak_match`)
- The user hasn't confirmed they want email delivery

## Example Usage

```
send_email(search_query="senior AI engineer NYC hybrid", max_jobs=10)
```
