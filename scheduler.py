"""scheduler.py — Background job search scheduler.

Reads search_config.yaml for titles, locations, and preferences.
Runs the full pipeline (search → fetch → analyze → email) on a configurable
interval, sending only new (never-before-sent) jobs to your inbox.

Usage:
  python scheduler.py            # run now, then repeat every N hours
  python scheduler.py --once     # run once and exit (useful for cron)
  nohup python scheduler.py &    # run in background, logs to logs/scheduler.log
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from analyzer import JobAnalyzer, UserPreferences
from config import load_config
from database import JobDatabase, DEFAULT_DB_PATH
from emailer import EmailSender
from scraper import LinkedInScraper, LinkedInScraperError

# ---------------------------------------------------------------------------
# Logging — console + rotating file
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "search_config.yaml"


def load_search_config() -> dict:
    if not CONFIG_PATH.exists():
        logger.error("search_config.yaml not found at %s", CONFIG_PATH)
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _extract_job_id(raw: dict) -> str | None:
    urn = raw.get("dashEntityUrn", "") or raw.get("entityUrn", "")
    m = re.search(r"(\d{5,})", urn)
    return m.group(1) if m else None


def run_pipeline() -> None:
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("Starting job search pipeline at %s", start.strftime("%Y-%m-%d %H:%M:%S"))

    # Load configs
    search_cfg = load_search_config()
    cfg = load_config()

    titles: list[str] = search_cfg["searches"]["titles"]
    locations: list[str] = search_cfg["searches"]["locations"]
    prefs_cfg = search_cfg.get("preferences", {})
    company_sizes: list[str] = prefs_cfg.get("company_sizes", ["startup", "small", "medium", "large", "enterprise"])
    min_score: float = float(prefs_cfg.get("min_relevance_score", 0.65))
    max_per_search: int = int(prefs_cfg.get("max_jobs_per_search", 15))

    total_combinations = len(titles) * len(locations)
    logger.info(
        "Config: %d title(s) × %d location(s) = %d searches | min_score=%.2f | max_per_search=%d",
        len(titles), len(locations), total_combinations, min_score, max_per_search,
    )

    db = JobDatabase(db_path=DEFAULT_DB_PATH)
    db.cleanup_expired()

    # Load parsed resume text if available
    analyzer = JobAnalyzer(
        api_key=cfg.anthropic_api_key,
        model=cfg.claude_model,
        db=db,
    )
    resume = db.get_latest_resume()
    if resume and resume.get("raw_text"):
        analyzer.candidate_profile = resume["raw_text"]
        logger.info("Loaded parsed resume text for candidate context: %s", resume["filename"])

    # Authenticate with LinkedIn
    logger.info("Authenticating with LinkedIn...")
    try:
        scraper = LinkedInScraper(
            email=cfg.linkedin_email,
            password=cfg.linkedin_password,
            db=db,
        )
    except LinkedInScraperError as exc:
        logger.error("LinkedIn authentication failed: %s", exc)
        db.close()
        return

    # Search each title × location combination
    combined_raw: dict[str, dict] = {}
    for title in titles:
        for location in locations:
            combo_query = f"{title} in {location}"
            logger.info("Searching: %s in %s ...", title, location)
            try:
                search_params = analyzer.generate_search_params(combo_query)
                logger.info("  Keywords: %s | Location: %s", search_params.keywords, search_params.location_name)
                raw = scraper.search_jobs(search_params)
                new_count = 0
                for r in raw:
                    jid = _extract_job_id(r)
                    if jid and jid not in combined_raw:
                        combined_raw[jid] = r
                        new_count += 1
                logger.info("  +%d new results (%d unique total)", new_count, len(combined_raw))
            except Exception as exc:
                logger.warning("  Search failed for '%s' in '%s': %s", title, location, exc)

    if not combined_raw:
        logger.warning("No raw results found across all searches. Skipping this run.")
        db.close()
        return

    logger.info("Total unique raw results: %d", len(combined_raw))

    # Fetch full job details
    max_jobs = max_per_search * total_combinations
    logger.info("Fetching up to %d job listings (rate-limited)...", max_jobs)
    try:
        jobs = scraper.fetch_full_listings(list(combined_raw.values()), max_jobs=max_jobs)
        logger.info("Fetched %d job listings.", len(jobs))
    except Exception as exc:
        logger.error("Failed to fetch job details: %s", exc)
        db.close()
        return

    if not jobs:
        logger.warning("No job details retrieved. Skipping this run.")
        db.close()
        return

    # Analyze with Claude
    logger.info("Analyzing jobs with Claude (min_score=%.2f)...", min_score)
    prefs = UserPreferences(
        natural_language_query=titles[0],
        preferred_company_sizes=company_sizes,
        min_relevance_score=min_score,
    )
    try:
        results = analyzer.analyze_jobs(jobs, prefs)
        logger.info("%d jobs passed the relevance filter.", len(results))
    except Exception as exc:
        logger.error("Analysis failed: %s", exc)
        db.close()
        return

    # Filter already-sent jobs
    sent_ids = db.get_sent_job_ids()
    new_results = [(job, analysis) for job, analysis in results if job.job_id not in sent_ids]
    logger.info(
        "%d new matches (filtered %d already sent)",
        len(new_results), len(results) - len(new_results),
    )

    if not new_results:
        logger.info("No new jobs to send. All matching jobs were already recommended.")
        db.close()
        return

    # Send email
    max_email = cfg.max_jobs_to_email
    to_send = new_results[:max_email]
    search_summary = ", ".join(titles[:3])
    if len(titles) > 3:
        search_summary += f" +{len(titles) - 3} more"

    logger.info("Sending email with %d jobs to %s...", len(to_send), cfg.gmail_recipient)
    emailer = EmailSender(
        gmail_address=cfg.gmail_address,
        gmail_app_password=cfg.gmail_app_password,
    )
    sent = emailer.send_job_results(
        recipient=cfg.gmail_recipient,
        search_query=search_summary,
        results=to_send,
    )

    if sent:
        db.mark_jobs_sent([job.job_id for job, _ in to_send])
        logger.info("Email sent successfully. Marked %d jobs as sent.", len(to_send))
    else:
        logger.error("Email send failed. Jobs NOT marked as sent — will retry next run.")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("Pipeline completed in %.1f seconds.", elapsed)
    db.close()


# ---------------------------------------------------------------------------
# Scheduler loop
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="LinkedIn job search scheduler")
    parser.add_argument("--once", action="store_true", help="Run once and exit (for cron)")
    args = parser.parse_args()

    if args.once:
        run_pipeline()
        return

    # Load interval from config
    search_cfg = load_search_config()
    interval_hours: float = float(search_cfg.get("schedule", {}).get("interval_hours", 1))
    interval_seconds = int(interval_hours * 3600)

    logger.info("Scheduler started. Interval: %.1f hour(s). Press Ctrl+C to stop.", interval_hours)

    while True:
        try:
            run_pipeline()
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
            break
        except Exception as exc:
            logger.exception("Unexpected error during pipeline run: %s", exc)

        next_run = datetime.now() + timedelta(seconds=interval_seconds)
        logger.info("Next run at %s. Sleeping...", next_run.strftime("%Y-%m-%d %H:%M:%S"))
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
            break


if __name__ == "__main__":
    main()
