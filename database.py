from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from typing import Optional

from scraper import CompanyInfo, JobListing, classify_company_size
from analyzer import JobAnalysis

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "job_cache.db"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class JobDatabase:
    """SQLite cache for job listings, company profiles, and analysis results."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company_name TEXT,
                company_id TEXT,
                company_staff_count INTEGER,
                company_industry TEXT,
                company_url TEXT,
                company_size_category TEXT,
                location TEXT,
                description TEXT,
                url TEXT,
                remote_allowed INTEGER DEFAULT 0,
                listed_at INTEGER,
                employment_type TEXT,
                experience_level TEXT,
                raw_data TEXT,
                fetched_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS companies (
                company_id TEXT PRIMARY KEY,
                name TEXT,
                staff_count INTEGER,
                industry TEXT,
                url TEXT,
                size_category TEXT,
                raw_data TEXT,
                fetched_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sent_jobs (
                job_id TEXT PRIMARY KEY,
                sent_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analyses (
                job_id TEXT,
                query_hash TEXT NOT NULL,
                relevance_score REAL,
                relevance_explanation TEXT,
                skills_match TEXT,
                skills_gap TEXT,
                pros TEXT,
                cons TEXT,
                recommendation TEXT,
                analyzed_at REAL NOT NULL,
                PRIMARY KEY (job_id, query_hash)
            );
        """)

    def close(self) -> None:
        self._conn.close()

    # -- Job cache ---------------------------------------------------------

    def get_job(self, job_id: str) -> Optional[JobListing]:
        """Return a cached JobListing if it exists and is not expired."""
        row = self._conn.execute(
            "SELECT * FROM jobs WHERE job_id = ? AND fetched_at > ?",
            (job_id, time.time() - self.ttl_seconds),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_job_listing(row)

    def save_job(self, listing: JobListing) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO jobs
               (job_id, title, company_name, company_id, company_staff_count,
                company_industry, company_url, company_size_category,
                location, description, url, remote_allowed, listed_at,
                employment_type, experience_level, raw_data, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing.job_id, listing.title,
                listing.company.name, listing.company.id,
                listing.company.staff_count, listing.company.industry,
                listing.company.url, listing.company.size_category,
                listing.location, listing.description, listing.url,
                int(listing.remote_allowed), listing.listed_at,
                listing.employment_type, listing.experience_level,
                json.dumps(listing.raw_data), time.time(),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_job_listing(row: sqlite3.Row) -> JobListing:
        company = CompanyInfo(
            name=row["company_name"],
            id=row["company_id"],
            staff_count=row["company_staff_count"],
            industry=row["company_industry"],
            url=row["company_url"],
            size_category=row["company_size_category"],
        )
        return JobListing(
            job_id=row["job_id"],
            title=row["title"],
            company=company,
            location=row["location"],
            description=row["description"],
            url=row["url"],
            remote_allowed=bool(row["remote_allowed"]),
            listed_at=row["listed_at"],
            employment_type=row["employment_type"],
            experience_level=row["experience_level"],
            raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
        )

    # -- Company cache -----------------------------------------------------

    def get_company(self, company_id: str) -> Optional[dict]:
        """Return cached company profile dict, or None."""
        row = self._conn.execute(
            "SELECT * FROM companies WHERE company_id = ? AND fetched_at > ?",
            (company_id, time.time() - self.ttl_seconds),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["raw_data"]) if row["raw_data"] else {}

    def save_company(self, company_id: str, profile: dict) -> None:
        staff_count = (
            profile.get("staffCount")
            or profile.get("staffCountRange", {}).get("start")
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO companies
               (company_id, name, staff_count, industry, url,
                size_category, raw_data, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company_id,
                profile.get("name", "Unknown"),
                staff_count,
                profile.get("industry"),
                profile.get("companyPageUrl", ""),
                classify_company_size(staff_count),
                json.dumps(profile),
                time.time(),
            ),
        )
        self._conn.commit()

    # -- Analysis cache ----------------------------------------------------

    @staticmethod
    def _compute_query_hash(query: str, preferences_sizes: list[str]) -> str:
        key = query + "|" + ",".join(sorted(preferences_sizes))
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def get_analysis(
        self, job_id: str, query: str, preferences_sizes: list[str]
    ) -> Optional[JobAnalysis]:
        """Return cached analysis if it matches current query, else None."""
        qhash = self._compute_query_hash(query, preferences_sizes)
        row = self._conn.execute(
            "SELECT * FROM analyses WHERE job_id = ? AND query_hash = ? AND analyzed_at > ?",
            (job_id, qhash, time.time() - self.ttl_seconds),
        ).fetchone()
        if row is None:
            return None
        return JobAnalysis(
            job_id=row["job_id"],
            relevance_score=row["relevance_score"],
            relevance_explanation=row["relevance_explanation"],
            skills_match=json.loads(row["skills_match"]),
            skills_gap=json.loads(row["skills_gap"]),
            pros=json.loads(row["pros"]),
            cons=json.loads(row["cons"]),
            recommendation=row["recommendation"],
        )

    def save_analysis(
        self, analysis: JobAnalysis, query: str, preferences_sizes: list[str]
    ) -> None:
        qhash = self._compute_query_hash(query, preferences_sizes)
        self._conn.execute(
            """INSERT OR REPLACE INTO analyses
               (job_id, query_hash, relevance_score, relevance_explanation,
                skills_match, skills_gap, pros, cons, recommendation, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis.job_id, qhash, analysis.relevance_score,
                analysis.relevance_explanation,
                json.dumps(analysis.skills_match), json.dumps(analysis.skills_gap),
                json.dumps(analysis.pros), json.dumps(analysis.cons),
                analysis.recommendation, time.time(),
            ),
        )
        self._conn.commit()

    # -- Sent jobs tracking ------------------------------------------------

    def get_sent_job_ids(self) -> set[str]:
        """Return job IDs that have already been emailed to the user."""
        rows = self._conn.execute("SELECT job_id FROM sent_jobs").fetchall()
        return {row["job_id"] for row in rows}

    def mark_jobs_sent(self, job_ids: list[str]) -> None:
        """Record that these jobs have been emailed."""
        now = time.time()
        self._conn.executemany(
            "INSERT OR IGNORE INTO sent_jobs (job_id, sent_at) VALUES (?, ?)",
            [(jid, now) for jid in job_ids],
        )
        self._conn.commit()

    # -- Maintenance -------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Delete rows older than TTL. Returns count of deleted rows."""
        cutoff = time.time() - self.ttl_seconds
        c1 = self._conn.execute("DELETE FROM jobs WHERE fetched_at < ?", (cutoff,)).rowcount
        c2 = self._conn.execute("DELETE FROM companies WHERE fetched_at < ?", (cutoff,)).rowcount
        c3 = self._conn.execute("DELETE FROM analyses WHERE analyzed_at < ?", (cutoff,)).rowcount
        self._conn.commit()
        total = c1 + c2 + c3
        if total > 0:
            logger.info("Cleaned up %d expired cache entries", total)
        return total
