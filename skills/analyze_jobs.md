# Analyze Jobs Skill

Score and rank fetched job listings by relevance to the candidate's profile using Claude AI.

## Tool: `analyze_jobs`

**Purpose**: Send fetched job listings to Claude for analysis. Claude scores each job 0.0–1.0 based on the candidate's actual background (skills, experience, domain fit), identifies matched/missing skills, and assigns a recommendation.

**Parameters**:
- `search_query` (string, required): The original natural language query (e.g., `"senior AI engineer in New York"`). Used as context for scoring.
- `min_score` (float, optional): Minimum relevance score to include in results. Range 0.0–1.0. Default: 0.6.
- `company_sizes` (string, optional): Comma-separated list of preferred sizes. Options: `startup`, `small`, `medium`, `large`, `enterprise`. Default: all sizes.

**Returns**: JSON with:
- `total_analyzed`: total jobs analyzed
- `new_matches`: jobs not previously sent to the user
- `filtered_already_sent`: jobs skipped (already recommended in a prior run)
- `top_results`: list of ranked jobs with score, recommendation, explanation, skill match/gap, and URL

## Scoring Guide

| Score | Meaning |
|-------|---------|
| 0.9–1.0 | Direct match to core expertise (RAG, agentic AI, LLM engineering) |
| 0.7–0.89 | Good overlap, minor gaps or domain stretch |
| 0.5–0.69 | Partial match — relevant but significant gaps |
| < 0.5 | Weak match — different role type, seniority, or stack |

## Recommendations

- `strong_match`: Score ≥ 0.85, role maps directly to candidate strengths
- `good_match`: Score ≥ 0.70, solid fit with minor concerns
- `weak_match`: Score ≥ 0.50, worth noting but not ideal
- `no_match`: Score < 0.50, do not recommend

## Guidelines

- Always call `fetch_job_details` before this tool.
- Use `min_score=0.6` as the default threshold — adjust based on user preference.
- Jobs already sent in previous runs are automatically filtered out (deduplication).
- Analysis results are cached by `(job_id, query_hash)` — re-running with the same query uses cached scores.
- Present results ranked by score with clear explanations. Highlight the top 5–10 to the user.

## Example Usage

```
analyze_jobs(search_query="senior AI engineer NYC hybrid", min_score=0.65, company_sizes="startup,small,medium,large")
```
