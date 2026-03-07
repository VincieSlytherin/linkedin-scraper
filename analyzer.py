from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from anthropic import Anthropic

from scraper import JobListing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AnalyzerError(Exception):
    pass


class SearchParamGenerationError(AnalyzerError):
    pass


class JobAnalysisError(AnalyzerError):
    pass


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SearchParams:
    keywords: str
    location_name: str
    remote: Optional[list[str]] = None
    experience: Optional[list[str]] = None
    job_type: Optional[list[str]] = None
    listed_at: int = 2592000  # 30 days
    limit: int = 50


@dataclass
class UserPreferences:
    natural_language_query: str
    preferred_company_sizes: list[str] = field(
        default_factory=lambda: ["startup", "small", "medium", "large", "enterprise"]
    )
    min_relevance_score: float = 0.6


@dataclass
class JobAnalysis:
    job_id: str
    relevance_score: float
    relevance_explanation: str
    skills_match: list[str]
    skills_gap: list[str]
    pros: list[str]
    cons: list[str]
    recommendation: str  # strong_match | good_match | weak_match | no_match


# ---------------------------------------------------------------------------
# Claude-powered analyzer
# ---------------------------------------------------------------------------

SEARCH_TOOL = {
    "name": "create_linkedin_search",
    "description": (
        "Create structured LinkedIn job search parameters "
        "from a natural language job description."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "string",
                "description": (
                    "LinkedIn search keywords. Keep it SIMPLE — use 2-5 words that "
                    "describe the core role. Do NOT use boolean operators (AND/OR). "
                    "LinkedIn search works best with plain keywords. "
                    "Examples: 'AI Engineer', 'Senior Backend Engineer Python', "
                    "'Generative AI Engineer', 'Machine Learning Engineer'"
                ),
            },
            "location_name": {
                "type": "string",
                "description": "City and state/country. Example: 'San Francisco, CA'",
            },
            "remote": {
                "type": "array",
                "items": {"type": "string", "enum": ["1", "2", "3"]},
                "description": "'1'=on-site, '2'=remote, '3'=hybrid. Omit for no filter.",
            },
            "experience": {
                "type": "array",
                "items": {"type": "string", "enum": ["1", "2", "3", "4", "5", "6"]},
                "description": (
                    "'1'=internship, '2'=entry, '3'=associate, "
                    "'4'=mid-senior, '5'=director, '6'=executive"
                ),
            },
            "job_type": {
                "type": "array",
                "items": {"type": "string", "enum": ["F", "P", "C", "T", "I", "V"]},
                "description": (
                    "'F'=full-time, 'P'=part-time, 'C'=contract, "
                    "'T'=temporary, 'I'=internship, 'V'=volunteer"
                ),
            },
            "listed_at": {
                "type": "integer",
                "description": "Max posting age in seconds. 86400=1d, 604800=7d, 2592000=30d.",
            },
        },
        "required": ["keywords", "location_name"],
    },
}

SEARCH_SYSTEM_PROMPT = """\
You are a LinkedIn job search expert. Given a natural language description of \
the kind of job a person is looking for, extract structured search parameters \
for the LinkedIn Jobs API.

Rules:
- keywords: Keep it SIMPLE. Use 2-5 plain words for the core role. \
Do NOT use boolean operators (AND/OR/NOT) or parentheses — LinkedIn's API \
works best with simple keyword phrases. \
Good: "Generative AI Engineer", "Senior Python Developer", "ML Engineer". \
Bad: "(AI OR ML) AND (Senior OR Lead)".
- location_name: Extract location. If none specified, use "United States".
- remote: Only include if user mentions remote/hybrid/on-site preference.
- experience: Map seniority to codes. "Senior"=["4"], "Lead/Principal"=["4","5"], \
"Junior/Entry"=["2"]. If no seniority mentioned, omit this field.
- job_type: Only include if user mentions full-time, part-time, contract, etc.
- listed_at: Default to 2592000 (30 days) unless user specifies recency.

Call the create_linkedin_search tool with your extracted parameters."""

CANDIDATE_PROFILE = """\
## Candidate Background

**Role**: AI Engineer (2+ years production experience)
**Visa**: H1B holder, USA-based, open to relocation

**Core strengths**:
- Production RAG systems: multimodal ingestion, hybrid semantic search, metadata-first retrieval, \
citation-grounded generation, hallucination mitigation. Deployed to 60+ enterprise users.
- Agentic / multi-agent systems: LangChain, LangGraph, function-calling architectures, \
LLM orchestration, structured execution graphs.
- LLM reliability: reduced execution errors from ~30% to ~5% by redesigning pure LLM pipelines \
into hybrid function-calling architectures.
- Multimodal document intelligence: OCR + vision models, hierarchical Markdown reconstruction, \
scanned document parsing.
- Data engineering at scale: PySpark (billions of records), Polars lazy execution, Parquet, \
zero-copy schema inspection, predicate pushdown.
- ML: PyTorch, Transformers, Bayesian hyperparameter optimization, SHAP attribution, \
attention-based NLP, MedLLAMA fine-tuning.

**Infrastructure**: AWS (Bedrock), Databricks, Docker, Kubernetes, Terraform, MLflow, CI/CD

**Model providers used**: Claude (Bedrock), ChatGPT, Gemini

**Languages**: Python (primary), SQL, Java, C++, Bash

**Domain experience**: Regulated financial / reinsurance environments (RGA), actuarial systems, \
underwriting decision engines, compliance analysis

**Education**: M.S. Computational Data Science, Carnegie Mellon University (GPA 3.85); \
B.S. Data Science, Duke Kunshan University (GPA 3.86)

**What fits well**:
- Senior / mid-senior AI Engineer, Applied AI Engineer, ML Engineer roles
- Companies building production AI systems, not just research
- Roles requiring RAG, agentic workflows, LLM orchestration, or multimodal pipelines
- Regulated industries (finance, insurance, healthcare, legal) are a strong fit
- Roles requiring both engineering depth (latency, reliability, scale) and AI expertise

**What does NOT fit**:
- Pure data science / analytics roles with no AI/LLM component
- Pure SWE roles with no ML/AI component
- Research-only positions (no production deployment)
- Junior roles
- Roles requiring extensive hardware/chip-level ML (e.g., CUDA kernel engineering)
"""

ANALYSIS_SYSTEM_PROMPT = """\
You are a precise job matching analyst evaluating roles for a specific candidate.

{candidate_profile}

The candidate is currently looking for: "{query}"
Preferred company sizes: {sizes}

Analyze each job listing and return a JSON array. For each job:
- job_id: string
- relevance_score: float 0.0–1.0 — score based on the candidate's ACTUAL background above, \
not just keyword overlap. A role requiring skills the candidate clearly has should score high \
even if the job description uses different terminology.
- relevance_explanation: string — 1-2 sentences explaining the match quality against this \
specific candidate's background
- skills_match: list[string] — candidate's skills that directly match job requirements
- skills_gap: list[string] — genuine gaps (skills the job requires that the candidate \
demonstrably lacks — be conservative, do not list skills the candidate likely has)
- pros: list[string] — concrete reasons this role suits this candidate
- cons: list[string] — genuine concerns (visa requirements, seniority mismatch, domain mismatch, etc.)
- recommendation: one of "strong_match", "good_match", "weak_match", "no_match"

Scoring guide:
  0.9–1.0  Role maps directly onto candidate's core expertise (RAG, agentic, LLM eng, multimodal)
  0.7–0.89 Good overlap with minor gaps or domain stretch
  0.5–0.69 Partial match — relevant skills but significant gaps or role mismatch
  <0.5     Weak match — different role type, seniority, or tech stack

Be strict: a generic "Software Engineer" or "Data Analyst" role should score below 0.5 \
even if it mentions AI. Reward roles that specifically value production AI systems experience.

Return ONLY a valid JSON array. No markdown fences, no extra text."""


class JobAnalyzer:
    """Uses Claude to generate search queries and analyze job listings."""

    ANALYSIS_BATCH_SIZE = 10

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        db=None,
        candidate_profile: str | None = None,
    ) -> None:
        self.client = Anthropic(api_key=api_key)
        self.model = model
        self._db = db
        # Use provided resume-based profile, fall back to hardcoded one
        self.candidate_profile = candidate_profile or CANDIDATE_PROFILE

    # -- resume profile extraction --------------------------------------

    def extract_profile_from_resume(self, resume_text: str) -> str:
        """Use Claude to extract a structured candidate profile from resume text."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=(
                "You are an expert resume analyst. Extract a structured candidate profile "
                "from the resume below. Format it as concise markdown covering:\n"
                "- Current role/level and years of experience\n"
                "- Core technical skills (be specific: frameworks, tools, languages)\n"
                "- Domain expertise and industry experience\n"
                "- Education\n"
                "- What types of roles they are best suited for\n"
                "- What does NOT fit (role types, seniority levels, tech stacks to avoid)\n"
                "- Any important job-search constraints (visa, location, etc.)\n\n"
                "Be specific and factual. Output ONLY the profile markdown, no preamble."
            ),
            messages=[{"role": "user", "content": resume_text}],
        )
        return response.content[0].text.strip()

    # -- search parameter generation ------------------------------------

    def generate_search_params(self, user_input: str) -> SearchParams:
        """Convert natural-language job description into SearchParams."""
        try:
            return self._generate_via_tool_use(user_input)
        except Exception as exc:
            logger.warning("Tool-use generation failed (%s), trying fallback", exc)
            try:
                return self._generate_via_json_fallback(user_input)
            except Exception as exc2:
                logger.warning("JSON fallback failed (%s), using raw input", exc2)
                return SearchParams(keywords=user_input, location_name="United States")

    def _generate_via_tool_use(self, user_input: str) -> SearchParams:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SEARCH_SYSTEM_PROMPT,
            tools=[SEARCH_TOOL],
            tool_choice={"type": "tool", "name": "create_linkedin_search"},
            messages=[{"role": "user", "content": user_input}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "create_linkedin_search":
                return self._parse_search_params(block.input)
        raise SearchParamGenerationError("No tool_use block in response")

    def _generate_via_json_fallback(self, user_input: str) -> SearchParams:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=(
                "Extract LinkedIn job search parameters from the user's description. "
                "Return a JSON object with keys: keywords, location_name, and optionally "
                "remote, experience, job_type, listed_at. Return ONLY valid JSON."
            ),
            messages=[{"role": "user", "content": user_input}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        return self._parse_search_params(data)

    @staticmethod
    def _parse_search_params(data: dict) -> SearchParams:
        return SearchParams(
            keywords=data["keywords"],
            location_name=data.get("location_name", "United States"),
            remote=data.get("remote"),
            experience=data.get("experience"),
            job_type=data.get("job_type"),
            listed_at=data.get("listed_at", 604800),
            limit=data.get("limit", 50),
        )

    # -- job analysis ---------------------------------------------------

    def analyze_jobs(
        self,
        jobs: list[JobListing],
        preferences: UserPreferences,
    ) -> list[tuple[JobListing, JobAnalysis]]:
        """Analyze, filter, and rank job listings."""
        all_analyses: list[tuple[JobListing, JobAnalysis]] = []
        jobs_to_analyze: list[JobListing] = []

        # Check cache for each job
        for job in jobs:
            if self._db is not None:
                cached = self._db.get_analysis(
                    job.job_id,
                    preferences.natural_language_query,
                    preferences.preferred_company_sizes,
                )
                if cached is not None:
                    all_analyses.append((job, cached))
                    continue
            jobs_to_analyze.append(job)

        if all_analyses:
            logger.info(
                "Loaded %d cached analyses, %d jobs need fresh analysis",
                len(all_analyses), len(jobs_to_analyze),
            )

        # Analyze uncached jobs in batches
        for i in range(0, len(jobs_to_analyze), self.ANALYSIS_BATCH_SIZE):
            batch = jobs_to_analyze[i : i + self.ANALYSIS_BATCH_SIZE]
            logger.info(
                "Analyzing batch %d–%d of %d uncached jobs",
                i + 1, min(i + self.ANALYSIS_BATCH_SIZE, len(jobs_to_analyze)),
                len(jobs_to_analyze),
            )
            try:
                analyses = self._analyze_batch(batch, preferences)
                for _job, analysis in analyses:
                    if self._db is not None:
                        self._db.save_analysis(
                            analysis,
                            preferences.natural_language_query,
                            preferences.preferred_company_sizes,
                        )
                all_analyses.extend(analyses)
            except JobAnalysisError as exc:
                logger.warning("Batch analysis failed: %s — skipping batch", exc)

        # Filter by company size preference
        filtered = [
            (job, analysis)
            for job, analysis in all_analyses
            if (
                job.company.size_category in preferences.preferred_company_sizes
                or job.company.size_category == "unknown"
            )
        ]

        # Filter by minimum relevance score
        filtered = [
            (job, analysis)
            for job, analysis in filtered
            if analysis.relevance_score >= preferences.min_relevance_score
        ]

        # Sort by score descending
        filtered.sort(key=lambda pair: pair[1].relevance_score, reverse=True)
        return filtered

    def _analyze_batch(
        self,
        jobs: list[JobListing],
        preferences: UserPreferences,
    ) -> list[tuple[JobListing, JobAnalysis]]:
        """Send a batch of jobs to Claude for analysis."""
        jobs_payload = []
        for job in jobs:
            jobs_payload.append({
                "job_id": job.job_id,
                "title": job.title,
                "company": job.company.name,
                "company_size": job.company.size_category or "unknown",
                "staff_count": job.company.staff_count,
                "location": job.location,
                "remote": job.remote_allowed,
                "employment_type": job.employment_type,
                "description": job.description[:2000],
            })

        system = ANALYSIS_SYSTEM_PROMPT.format(
            candidate_profile=self.candidate_profile,
            query=preferences.natural_language_query,
            sizes=", ".join(preferences.preferred_company_sizes),
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[
                {"role": "user", "content": json.dumps(jobs_payload, indent=2)},
            ],
        )

        text = response.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            raw_analyses = json.loads(text)
        except json.JSONDecodeError as exc:
            raise JobAnalysisError(f"Failed to parse analysis JSON: {exc}") from exc

        # Map analyses back to jobs
        analysis_by_id = {}
        for item in raw_analyses:
            try:
                analysis_by_id[str(item["job_id"])] = JobAnalysis(
                    job_id=str(item["job_id"]),
                    relevance_score=float(item.get("relevance_score", 0)),
                    relevance_explanation=item.get("relevance_explanation", ""),
                    skills_match=item.get("skills_match", []),
                    skills_gap=item.get("skills_gap", []),
                    pros=item.get("pros", []),
                    cons=item.get("cons", []),
                    recommendation=item.get("recommendation", "no_match"),
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping malformed analysis entry: %s", exc)

        results: list[tuple[JobListing, JobAnalysis]] = []
        for job in jobs:
            if job.job_id in analysis_by_id:
                results.append((job, analysis_by_id[job.job_id]))
            else:
                logger.warning("No analysis returned for job %s", job.job_id)
        return results
