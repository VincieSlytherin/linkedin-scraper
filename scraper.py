from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from linkedin_api import Linkedin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LinkedInScraperError(Exception):
    pass


class AuthenticationError(LinkedInScraperError):
    pass


class RateLimitError(LinkedInScraperError):
    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class CompanyInfo:
    name: str
    id: str
    staff_count: Optional[int] = None
    industry: Optional[str] = None
    url: Optional[str] = None
    size_category: Optional[str] = None


@dataclass
class JobListing:
    job_id: str
    title: str
    company: CompanyInfo
    location: str
    description: str
    url: str
    remote_allowed: bool = False
    listed_at: Optional[int] = None
    employment_type: Optional[str] = None
    experience_level: Optional[str] = None
    raw_data: dict = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def classify_company_size(staff_count: Optional[int]) -> str:
    """Map employee count to a human-readable size category."""
    if staff_count is None:
        return "unknown"
    if staff_count <= 50:
        return "startup"
    if staff_count <= 200:
        return "small"
    if staff_count <= 1000:
        return "medium"
    if staff_count <= 10000:
        return "large"
    return "enterprise"


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class LinkedInScraper:
    """Wraps the unofficial linkedin-api library for job searching."""

    REQUEST_DELAY = 2.0          # seconds between API calls
    MAX_RETRIES = 3
    BACKOFF_BASE = 5             # seconds; doubles each retry

    COOKIE_FILE = "linkedin_cookies.json"

    def __init__(self, email: str, password: str) -> None:
        import json
        from pathlib import Path
        from requests.cookies import cookiejar_from_dict

        cookie_path = Path(self.COOKIE_FILE)

        # Try cookie-based auth first (bypasses CHALLENGE errors)
        if cookie_path.exists():
            try:
                with open(cookie_path) as f:
                    cookie_dict = json.load(f)
                # linkedin-api expects a RequestsCookieJar, not a plain dict
                cookie_jar = cookiejar_from_dict(cookie_dict)
                self._api = Linkedin(email, password, cookies=cookie_jar)
                logger.info("Authenticated with saved cookies")
                self._last_request_time: float = 0.0
                return
            except Exception as exc:
                logger.warning("Saved cookies failed (%s), trying fresh login...", exc)
                cookie_path.unlink(missing_ok=True)

        # Fresh login
        try:
            self._api = Linkedin(email, password)
        except Exception as exc:
            error_msg = str(exc)
            if "CHALLENGE" in error_msg.upper():
                raise AuthenticationError(
                    "LinkedIn requires verification (CHALLENGE). "
                    "Please:\n"
                    "  1. Log into LinkedIn in your browser on this machine\n"
                    "  2. Complete any CAPTCHA/email verification\n"
                    "  3. Run: python extract_cookies.py\n"
                    "  4. Then run: python main.py"
                ) from exc
            raise AuthenticationError(
                f"LinkedIn authentication failed: {exc}"
            ) from exc

        # Save cookies for future runs
        try:
            cookies = self._api.client.session.cookies.get_dict()
            with open(cookie_path, "w") as f:
                json.dump(cookies, f)
            logger.info("Saved LinkedIn cookies for future runs")
        except Exception:
            logger.debug("Could not save cookies (non-critical)")

        self._last_request_time = 0.0

    # -- rate limiting --------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_DELAY:
            time.sleep(self.REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _call_with_retry(self, fn, *args, **kwargs):
        """Call *fn* with retries and exponential backoff."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                self._rate_limit()
                return fn(*args, **kwargs)
            except Exception as exc:
                wait = self.BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "API call %s failed (attempt %d/%d): %s  — retrying in %ds",
                    fn.__name__, attempt, self.MAX_RETRIES, exc, wait,
                )
                if attempt == self.MAX_RETRIES:
                    raise LinkedInScraperError(
                        f"{fn.__name__} failed after {self.MAX_RETRIES} attempts: {exc}"
                    ) from exc
                time.sleep(wait)

    # -- public API -----------------------------------------------------

    def search_jobs(self, search_params) -> list[dict]:
        """Search LinkedIn jobs using structured SearchParams."""
        # Strip commas from location — LinkedIn's internal query format uses
        # commas as separators, so "San Francisco, CA" breaks the API (HTTP 400).
        location = search_params.location_name.replace(",", "")

        kwargs: dict = {
            "keywords": search_params.keywords,
            "location_name": location,
            "limit": search_params.limit,
        }
        if search_params.remote:
            kwargs["remote"] = search_params.remote
        if search_params.experience:
            kwargs["experience"] = search_params.experience
        if search_params.job_type:
            kwargs["job_type"] = search_params.job_type
        if search_params.listed_at:
            kwargs["listed_at"] = search_params.listed_at

        logger.info("Searching LinkedIn: %s", kwargs)
        results = self._call_with_retry(self._api.search_jobs, **kwargs)
        logger.debug("Raw search returned %d results", len(results))
        if not results:
            # Retry with minimal params (just keywords, no filters)
            logger.info("No results with filters — retrying with keywords only...")
            results = self._call_with_retry(
                self._api.search_jobs,
                keywords=search_params.keywords,
                limit=search_params.limit,
            )
            logger.info("Broad search returned %d results", len(results))
        if results:
            logger.debug("Sample result keys: %s", list(results[0].keys()))
        # deduplicate by job id
        seen: set[str] = set()
        unique: list[dict] = []
        for r in results:
            jid = self._extract_job_id(r)
            if jid and jid not in seen:
                seen.add(jid)
                unique.append(r)
        return unique

    def fetch_full_listings(
        self, raw_results: list[dict], max_jobs: int = 50
    ) -> list[JobListing]:
        """Fetch detailed info for each raw search result."""
        listings: list[JobListing] = []
        for raw in raw_results[:max_jobs]:
            job_id = self._extract_job_id(raw)
            if not job_id:
                continue
            try:
                detail = self._call_with_retry(self._api.get_job, job_id)
            except LinkedInScraperError:
                logger.warning("Skipping job %s — could not fetch details", job_id)
                continue

            if not detail:
                continue

            # Build company info
            company_info = self._build_company_info(detail)

            # Build job listing
            description = (
                detail.get("description", {}).get("text", "")
                if isinstance(detail.get("description"), dict)
                else str(detail.get("description", ""))
            )
            listing = JobListing(
                job_id=job_id,
                title=detail.get("title", raw.get("title", "Unknown")),
                company=company_info,
                location=detail.get("formattedLocation", raw.get("formattedLocation", "Unknown")),
                description=description,
                url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                remote_allowed=bool(detail.get("workRemoteAllowed", False)),
                listed_at=detail.get("listedAt"),
                employment_type=detail.get("employmentType"),
                experience_level=detail.get("experienceLevel"),
                raw_data=detail,
            )
            listings.append(listing)
            logger.info(
                "Fetched [%d/%d] %s @ %s",
                len(listings), min(max_jobs, len(raw_results)),
                listing.title, listing.company.name,
            )
        return listings

    # -- internals ------------------------------------------------------

    def _build_company_info(self, detail: dict) -> CompanyInfo:
        """Extract company information from a job detail dict."""
        company_data = detail.get("companyDetails", {})
        # The structure can vary; try common paths
        company_resolved = (
            company_data.get("com.linkedin.voyager.deco.jobs.web.shared.WebCompactJobPostingCompany", {})
            or company_data
        )
        company_name = company_resolved.get("companyResolutionResult", {}).get("name", "Unknown")
        company_url = company_resolved.get("companyResolutionResult", {}).get("url", "")
        company_urn = company_resolved.get("company", "")

        # Try to get staff count from the company resolution
        staff_count = (
            company_resolved.get("companyResolutionResult", {}).get("staffCount")
            or company_resolved.get("companyResolutionResult", {}).get("staffCountRange", {}).get("start")
        )

        # If no staff count yet, try fetching company profile
        if staff_count is None and company_urn:
            public_id = self._extract_company_public_id(company_urn)
            if public_id:
                try:
                    company_profile = self._call_with_retry(self._api.get_company, public_id)
                    staff_count = (
                        company_profile.get("staffCount")
                        or company_profile.get("staffCountRange", {}).get("start")
                    )
                    if not company_name or company_name == "Unknown":
                        company_name = company_profile.get("name", company_name)
                    if not company_url:
                        company_url = company_profile.get("companyPageUrl", "")
                except LinkedInScraperError:
                    logger.debug("Could not fetch company profile for %s", company_urn)

        size_category = classify_company_size(staff_count)
        return CompanyInfo(
            name=company_name,
            id=company_urn,
            staff_count=staff_count,
            url=company_url,
            size_category=size_category,
        )

    @staticmethod
    def _extract_job_id(raw_job: dict) -> Optional[str]:
        urn = raw_job.get("dashEntityUrn", "") or raw_job.get("entityUrn", "")
        match = re.search(r"(\d{5,})", urn)
        return match.group(1) if match else None

    @staticmethod
    def _extract_company_public_id(company_urn: str) -> Optional[str]:
        """Extract a usable company identifier from a URN."""
        # URN like urn:li:fsd_company:12345 or urn:li:company:12345
        match = re.search(r"(\d+)$", company_urn)
        return match.group(1) if match else None
