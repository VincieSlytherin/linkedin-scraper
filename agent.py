"""agent.py — Claude Agent SDK-based LinkedIn job search agent.

Skills are loaded from skills/*.md files and injected into the system prompt.

Run with: python agent.py
       or: python agent.py "senior AI engineer roles in New York"
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    TextBlock,
    create_sdk_mcp_server,
    tool,
)

from analyzer import JobAnalyzer, UserPreferences
from config import load_config
from database import JobDatabase
from emailer import EmailSender
from scraper import LinkedInScraper

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Session state (shared across all tool calls in a single agent run)
# ---------------------------------------------------------------------------

class _Session:
    def __init__(self) -> None:
        self.config = load_config()
        self.db = JobDatabase()
        self.db.cleanup_expired()
        self.analyzer = JobAnalyzer(
            api_key=self.config.anthropic_api_key,
            model=self.config.claude_model,
            db=self.db,
        )
        # Use resume-based profile if available
        resume = self.db.get_latest_resume()
        if resume and resume.get("extracted_profile"):
            self.analyzer.candidate_profile = resume["extracted_profile"]
            logger.info("Loaded candidate profile from resume: %s", resume["filename"])

        self.scraper: LinkedInScraper | None = None
        self.raw_search_results: list[dict] = []
        self.fetched_jobs: list = []
        self.analysis_results: list = []


_session: _Session | None = None


def _get_session() -> _Session:
    global _session
    if _session is None:
        _session = _Session()
    return _session


def _extract_job_id(raw_job: dict) -> str | None:
    urn = raw_job.get("dashEntityUrn", "") or raw_job.get("entityUrn", "")
    m = re.search(r"(\d{5,})", urn)
    return m.group(1) if m else None


def _ensure_scraper(sess: _Session) -> None:
    """Initialize scraper synchronously (called inside run_in_executor)."""
    if sess.scraper is None:
        sess.scraper = LinkedInScraper(
            email=sess.config.linkedin_email,
            password=sess.config.linkedin_password,
            db=sess.db,
        )


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@tool(
    "search_jobs",
    "Search LinkedIn for job listings. Call this first with keywords and location.",
    {"keywords": str, "location": str, "limit": int},
)
async def search_jobs_tool(args: dict) -> dict:
    sess = _get_session()
    keywords = args["keywords"]
    location = args.get("location", "United States")
    limit = int(args.get("limit", 50))

    from analyzer import SearchParams
    search_params = SearchParams(keywords=keywords, location_name=location, limit=limit)

    loop = asyncio.get_event_loop()

    def _run():
        _ensure_scraper(sess)
        return sess.scraper.search_jobs(search_params)

    raw = await loop.run_in_executor(None, _run)
    sess.raw_search_results = raw

    summary = [
        {"job_id": _extract_job_id(r), "title": r.get("title", "Unknown")}
        for r in raw
        if _extract_job_id(r)
    ]
    return {"content": [{"type": "text", "text": json.dumps({
        "count": len(raw),
        "jobs": summary[:20],
    })}]}


@tool(
    "fetch_job_details",
    "Fetch full job descriptions and company info for search results. Call after search_jobs.",
    {"max_jobs": int},
)
async def fetch_jobs_tool(args: dict) -> dict:
    sess = _get_session()
    if not sess.raw_search_results:
        return {"content": [{"type": "text", "text": json.dumps({
            "error": "No search results in session. Call search_jobs first."
        })}]}

    max_jobs = int(args.get("max_jobs", sess.config.max_jobs_to_fetch))
    loop = asyncio.get_event_loop()

    jobs = await loop.run_in_executor(
        None,
        lambda: sess.scraper.fetch_full_listings(sess.raw_search_results, max_jobs=max_jobs),
    )
    sess.fetched_jobs = jobs

    summaries = [
        {
            "job_id": j.job_id,
            "title": j.title,
            "company": j.company.name,
            "size": j.company.size_category,
            "location": j.location,
            "remote": j.remote_allowed,
            "url": j.url,
        }
        for j in jobs
    ]
    return {"content": [{"type": "text", "text": json.dumps({
        "fetched": len(jobs),
        "jobs": summaries,
    })}]}


@tool(
    "analyze_jobs",
    "Score and rank fetched jobs by relevance to the candidate profile. Call after fetch_job_details.",
    {"search_query": str, "min_score": float, "company_sizes": str},
)
async def analyze_jobs_tool(args: dict) -> dict:
    sess = _get_session()
    if not sess.fetched_jobs:
        return {"content": [{"type": "text", "text": json.dumps({
            "error": "No fetched jobs in session. Call fetch_job_details first."
        })}]}

    search_query = args.get("search_query", "AI Engineer")
    min_score = float(args.get("min_score", 0.6))
    sizes_str = args.get("company_sizes", "startup,small,medium,large,enterprise")
    sizes = [s.strip() for s in sizes_str.split(",") if s.strip()]

    prefs = UserPreferences(
        natural_language_query=search_query,
        preferred_company_sizes=sizes,
        min_relevance_score=min_score,
    )

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None, lambda: sess.analyzer.analyze_jobs(sess.fetched_jobs, prefs)
    )

    # Filter already-sent jobs
    sent_ids = sess.db.get_sent_job_ids()
    new_results = [(job, analysis) for job, analysis in results if job.job_id not in sent_ids]
    sess.analysis_results = new_results

    top = [
        {
            "rank": i + 1,
            "job_id": job.job_id,
            "title": job.title,
            "company": job.company.name,
            "size": job.company.size_category,
            "score": round(analysis.relevance_score, 2),
            "recommendation": analysis.recommendation,
            "explanation": analysis.relevance_explanation,
            "skills_match": analysis.skills_match[:5],
            "skills_gap": analysis.skills_gap[:3],
            "url": job.url,
        }
        for i, (job, analysis) in enumerate(new_results[:20])
    ]
    return {"content": [{"type": "text", "text": json.dumps({
        "total_analyzed": len(results),
        "new_matches": len(new_results),
        "filtered_already_sent": len(results) - len(new_results),
        "top_results": top,
    })}]}


@tool(
    "send_email",
    "Send top job results to the user's email. Only call after analyze_jobs. Only for strong_match/good_match jobs.",
    {"search_query": str, "max_jobs": int},
)
async def send_email_tool(args: dict) -> dict:
    sess = _get_session()
    if not sess.analysis_results:
        return {"content": [{"type": "text", "text": json.dumps({
            "error": "No analysis results in session. Call analyze_jobs first."
        })}]}

    max_jobs = int(args.get("max_jobs", sess.config.max_jobs_to_email))
    search_query = args.get("search_query", "job search")
    top = sess.analysis_results[:max_jobs]

    emailer = EmailSender(
        gmail_address=sess.config.gmail_address,
        gmail_app_password=sess.config.gmail_app_password,
    )

    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(
        None,
        lambda: emailer.send_job_results(
            recipient=sess.config.gmail_recipient,
            search_query=search_query,
            results=top,
        ),
    )

    if success:
        job_ids = [job.job_id for job, _ in top]
        sess.db.mark_jobs_sent(job_ids)
        return {"content": [{"type": "text", "text": json.dumps({
            "success": True,
            "sent_to": sess.config.gmail_recipient,
            "jobs_sent": len(top),
            "job_ids": job_ids,
        })}]}

    return {"content": [{"type": "text", "text": json.dumps({
        "success": False,
        "error": "Email send failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env.",
    })}]}


@tool(
    "get_candidate_profile",
    "Get the candidate profile currently used for job matching.",
    {},
)
async def get_profile_tool(args: dict) -> dict:
    sess = _get_session()
    resume = sess.db.get_latest_resume()
    source = "resume" if (resume and resume.get("extracted_profile")) else "default"
    profile = sess.analyzer.candidate_profile
    return {"content": [{"type": "text", "text": json.dumps({
        "source": source,
        "profile_preview": profile[:600] + "..." if len(profile) > 600 else profile,
    })}]}


# ---------------------------------------------------------------------------
# Load skills/*.md into system prompt
# ---------------------------------------------------------------------------

def _load_skills() -> str:
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.exists():
        return ""
    parts = []
    for md_file in sorted(skills_dir.glob("*.md")):
        parts.append(f"### {md_file.stem.replace('_', ' ').title()}\n\n{md_file.read_text().strip()}")
    return "\n\n---\n\n".join(parts)


AGENT_SYSTEM_PROMPT = """\
You are a LinkedIn job search agent. Your goal is to find relevant job opportunities for the \
candidate based on their profile and preferences.

## Workflow

1. Call `search_jobs` with targeted keywords and location derived from the user's request.
2. Call `fetch_job_details` to get full listings (suggest max_jobs=25 to stay within rate limits).
3. Call `analyze_jobs` to score and rank jobs by relevance (use min_score=0.6 by default).
4. Present the top results clearly: title, company, score, key match/gap skills, and LinkedIn link.
5. Ask if the user wants to send results by email. If yes, call `send_email`.

## Presentation Format

For each top job, show:
- Rank, title, company (size), location, remote status
- Score (e.g. 85%) and recommendation (strong_match / good_match)
- 1-sentence explanation
- Matched skills | Missing skills
- LinkedIn URL

## Guidelines

- Keep keywords simple (2-5 words). Run a second search with broader terms if the first returns few results.
- Only recommend strong_match and good_match jobs in the email.
- Do not send email without user confirmation unless explicitly asked to.
- Already-sent jobs are automatically filtered — the user will only see new opportunities.
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_agent(user_query: str) -> None:
    skills_content = _load_skills()
    system_prompt = AGENT_SYSTEM_PROMPT
    if skills_content:
        system_prompt += f"\n\n## Skill Reference\n\n{skills_content}"

    server = create_sdk_mcp_server(
        "linkedin-job-search",
        tools=[
            search_jobs_tool,
            fetch_jobs_tool,
            analyze_jobs_tool,
            send_email_tool,
            get_profile_tool,
        ],
    )

    options = ClaudeAgentOptions(
        mcp_servers={"job-search": server},
        system_prompt=system_prompt,
        model="claude-opus-4-6",
        max_turns=20,
    )

    print(f"\nQuery: {user_query}\n{'=' * 60}")
    async with ClaudeSDKClient(options=options) as client:
        await client.query(user_query)
        async for message in client.receive_response():
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text, end="", flush=True)
    print()

    # Close DB
    if _session is not None:
        _session.db.close()


def main() -> None:
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        print("LinkedIn Job Search Agent")
        print("=" * 40)
        query = input("What kind of job are you looking for?\n> ").strip()
        if not query:
            print("No query provided.")
            sys.exit(1)

    asyncio.run(run_agent(query))


if __name__ == "__main__":
    main()
