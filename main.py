from __future__ import annotations

import logging
import sys

from analyzer import JobAnalyzer, UserPreferences, AnalyzerError
from config import load_config
from database import JobDatabase
from emailer import EmailSender
from scraper import LinkedInScraper, LinkedInScraperError


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_user_input() -> UserPreferences:
    """Collect job search preferences interactively."""
    print("=" * 60)
    print("  LinkedIn Job Scraper with Claude AI")
    print("=" * 60)
    print()

    # Required: job description
    query = ""
    while not query.strip():
        query = input("Describe the job you're looking for:\n> ").strip()
        if not query:
            print("Please enter a job description.\n")

    # Optional: company size
    print("\nCompany size preferences (comma-separated, or Enter for all):")
    print("  Options: startup, small, medium, large, enterprise")
    size_input = input("> ").strip()
    valid_sizes = {"startup", "small", "medium", "large", "enterprise"}
    if size_input:
        sizes = [s.strip().lower() for s in size_input.split(",")]
        sizes = [s for s in sizes if s in valid_sizes]
        if not sizes:
            print("  No valid sizes entered — using all sizes.")
            sizes = sorted(valid_sizes)
    else:
        sizes = sorted(valid_sizes)

    # Optional: minimum relevance score
    print("\nMinimum relevance score 0.0–1.0 (Enter for 0.6):")
    score_input = input("> ").strip()
    try:
        min_score = float(score_input) if score_input else 0.6
        min_score = max(0.0, min(1.0, min_score))
    except ValueError:
        min_score = 0.6

    print()
    return UserPreferences(
        natural_language_query=query,
        preferred_company_sizes=sizes,
        min_relevance_score=min_score,
    )


def print_summary(results: list[tuple]) -> None:
    """Print a ranked summary of results to the terminal."""
    print(f"\n  Top {len(results)} Job Matches")
    print("=" * 60)
    for i, (job, analysis) in enumerate(results, 1):
        bar_len = int(analysis.relevance_score * 20)
        score_bar = "#" * bar_len + "-" * (20 - bar_len)
        print(f"\n  [{i}] {job.title}")
        print(f"      Company:  {job.company.name} ({job.company.size_category or 'unknown'})")
        print(f"      Location: {job.location}{'  (Remote)' if job.remote_allowed else ''}")
        print(f"      Score:    [{score_bar}] {analysis.relevance_score:.0%}")
        print(f"      Match:    {analysis.recommendation.replace('_', ' ')}")
        if analysis.skills_match:
            print(f"      Skills:   {', '.join(analysis.skills_match[:5])}")
        if analysis.skills_gap:
            print(f"      Gap:      {', '.join(analysis.skills_gap[:3])}")
        print(f"      Link:     {job.url}")
        print(f"      Why:      {analysis.relevance_explanation}")
    print("\n" + "=" * 60)


def main() -> None:
    setup_logging()
    logger = logging.getLogger(__name__)

    # 1. Load config
    config = load_config()

    # 1b. Initialize database cache
    db = JobDatabase()
    db.cleanup_expired()
    logger.info("Job cache initialized (%s)", db.db_path)

    # 2. Collect user input
    preferences = get_user_input()

    # 3. Generate search params with Claude
    logger.info("Generating search parameters with Claude...")
    analyzer = JobAnalyzer(api_key=config.anthropic_api_key, model=config.claude_model, db=db)
    try:
        search_params = analyzer.generate_search_params(preferences.natural_language_query)
        logger.info(
            "Search params: keywords='%s', location='%s'",
            search_params.keywords, search_params.location_name,
        )
    except AnalyzerError as exc:
        logger.error("Failed to generate search parameters: %s", exc)
        sys.exit(1)

    # 4. Authenticate with LinkedIn and search
    logger.info("Authenticating with LinkedIn...")
    try:
        scraper = LinkedInScraper(
            email=config.linkedin_email,
            password=config.linkedin_password,
            db=db,
        )
    except LinkedInScraperError as exc:
        logger.error("LinkedIn authentication failed: %s", exc)
        sys.exit(1)

    logger.info("Searching for jobs...")
    try:
        raw_results = scraper.search_jobs(search_params)
        logger.info("Found %d raw results", len(raw_results))
    except LinkedInScraperError as exc:
        logger.error("Job search failed: %s", exc)
        sys.exit(1)

    if not raw_results:
        logger.warning("No jobs found matching your criteria.")
        sys.exit(0)

    # 5. Fetch full job details (rate-limited)
    logger.info("Fetching full job details (this may take a few minutes)...")
    jobs = scraper.fetch_full_listings(raw_results, max_jobs=config.max_jobs_to_fetch)
    logger.info("Successfully fetched details for %d jobs", len(jobs))

    if not jobs:
        logger.warning("Could not fetch details for any jobs.")
        sys.exit(0)

    # 6. Analyze and rank with Claude
    logger.info("Analyzing jobs with Claude...")
    try:
        results = analyzer.analyze_jobs(jobs, preferences)
        logger.info("Analysis complete: %d jobs passed filters", len(results))
    except AnalyzerError as exc:
        logger.error("Job analysis failed: %s", exc)
        sys.exit(1)

    if not results:
        logger.warning("No jobs matched your preferences after analysis.")
        sys.exit(0)

    # Filter out jobs already sent in previous runs
    sent_ids = db.get_sent_job_ids()
    new_results = [(job, analysis) for job, analysis in results if job.job_id not in sent_ids]
    if len(new_results) < len(results):
        logger.info(
            "Filtered out %d previously sent jobs, %d new jobs remaining",
            len(results) - len(new_results), len(new_results),
        )

    if not new_results:
        logger.warning("All matching jobs were already sent in previous runs.")
        sys.exit(0)

    # Limit to top N for email
    top_results = new_results[: config.max_jobs_to_email]

    # 7. Email results
    logger.info("Sending top %d results to %s...", len(top_results), config.gmail_recipient)
    emailer = EmailSender(
        gmail_address=config.gmail_address,
        gmail_app_password=config.gmail_app_password,
    )
    email_sent = emailer.send_job_results(
        recipient=config.gmail_recipient,
        search_query=preferences.natural_language_query,
        results=top_results,
    )
    if email_sent:
        logger.info("Email sent successfully!")
        db.mark_jobs_sent([job.job_id for job, _ in top_results])
    else:
        logger.warning("Failed to send email. See results below.")

    # 8. Terminal summary
    print_summary(top_results)

    # 9. Close database
    db.close()


if __name__ == "__main__":
    main()
