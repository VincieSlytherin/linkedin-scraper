# Search Jobs Skill

Search LinkedIn for job listings using structured keywords and location. Supports multiple job titles and multiple locations in a single run.

## Tool: `search_jobs`

**Purpose**: Trigger a LinkedIn job search and return a list of raw job IDs with basic metadata. Call once per title × location combination, then merge results before analysis.

**Parameters**:
- `keywords` (string, required): 2–5 plain words describing the core role. Do NOT use boolean operators. Examples: `"AI Engineer"`, `"Senior Backend Python"`, `"Machine Learning Engineer"`.
- `location` (string, required): City and state/country. Example: `"San Francisco, CA"`. Use `"United States"` for a national search.
- `limit` (integer, optional): Max results per search. Default: 50.

**Returns**: JSON with `count` (total results) and `jobs` (list of `{job_id, title}`).

## Multi-Title / Multi-Location Search

When searching across multiple roles or areas, call `search_jobs` once per combination and deduplicate by `job_id` before fetching details.

**Example**: 3 titles × 2 locations = 6 `search_jobs` calls:
```
search_jobs(keywords="Senior AI Engineer",      location="San Francisco, CA")
search_jobs(keywords="Senior AI Engineer",      location="New York, NY")
search_jobs(keywords="ML Engineer",             location="San Francisco, CA")
search_jobs(keywords="ML Engineer",             location="New York, NY")
search_jobs(keywords="Applied AI Engineer",     location="San Francisco, CA")
search_jobs(keywords="Applied AI Engineer",     location="New York, NY")
```

Collect all results, deduplicate by `job_id`, then call `fetch_job_details` once on the merged list.

## Guidelines

- Keep keywords simple — 2–5 plain words. LinkedIn's API works best with short keyword phrases.
- For seniority, include it in keywords: `"Senior AI Engineer"` not just `"AI Engineer"`.
- For remote roles: use `"United States"` as location and note remote preference for the analyze step.
- If a search returns 0 results, retry with broader keywords (remove seniority qualifier).
- Do not exceed 5 titles or 5 locations per run — that's 25 searches, which is slow and risks rate limiting.
- After all searches, always deduplicate before fetching — the same job can appear in multiple searches.
