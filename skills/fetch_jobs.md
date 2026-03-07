# Fetch Job Details Skill

Fetch full job descriptions, company info, and metadata for raw search results.

## Tool: `fetch_job_details`

**Purpose**: Hydrate the raw job IDs from `search_jobs` into full `JobListing` objects with descriptions, company employee count, remote status, and experience level. Results are cached in SQLite to avoid redundant API calls on subsequent runs.

**Parameters**:
- `max_jobs` (integer, optional): Maximum number of jobs to fetch details for. Default: 50 (from config). Keep at 20–30 to avoid LinkedIn rate limits.

**Returns**: JSON with `fetched` (count) and `jobs` (list of `{job_id, title, company, size, location, remote, url}`).

## Guidelines

- Always call `search_jobs` before this tool — `fetch_job_details` uses the stored search results from the current session.
- Fetching is rate-limited (4s+ between requests) to avoid LinkedIn blocking. Expect this to take 1–3 minutes for 20–30 jobs.
- The cache (SQLite) prevents re-fetching jobs seen within the last 7 days — cache hits are instant.
- Company size categories: `startup` (≤50 employees), `small` (≤200), `medium` (≤1000), `large` (≤10000), `enterprise` (10000+).
- If fetching fails for a specific job, it is skipped — this is normal behavior.
- Prefer fetching 20–30 jobs at a time rather than all 50 to reduce rate-limit risk.

## Example Usage

After a `search_jobs` call:
```
fetch_job_details(max_jobs=25)
```
