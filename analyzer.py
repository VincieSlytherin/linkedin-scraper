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
You are a LinkedIn job search expert. Build structured search parameters for the \
LinkedIn Jobs API using two inputs:
1. Resume / candidate context (below)
2. The user's current job search request

Treat the candidate context as the source of truth for level, constraints, and target roles. \
Use the user's request to narrow or prioritize, not to override the candidate's positioning.

Candidate context:
{candidate_resume_text}

## Role Tier Reference (use this to pick the best keywords)

Tier 1 keywords (best match — prefer these):
  "Applied AI Engineer", "GenAI Engineer", "AI Engineer", "Generative AI Engineer", \
"LLM Engineer"

Tier 2 keywords (also strong):
  "Machine Learning Engineer", "ML Engineer"

Tier 3 keywords (only if user explicitly asks):
  "AI Platform Engineer"

NEVER generate keywords for: "AI Research Scientist", "Staff AI Engineer", \
"Principal AI Engineer", "Research Engineer" — these are outside the candidate's \
target tier.

## Rules

- keywords: 2–5 plain words from the Tier 1/2 list above, aligned with the user's request. \
Do NOT use boolean operators (AND/OR/NOT). \
Good: "AI Engineer", "Generative AI Engineer". Bad: "(AI OR ML) AND Senior".
- location_name: Extract from user request. Default to "United States" if unspecified.
- remote: Include only if user mentions remote/hybrid/on-site.
- experience: This candidate is mid-level (2+ years). Default to ["3","4"] \
(associate + mid-senior). Use ["4"] if user requests "senior". Do NOT use ["5","6"].
- job_type: Include only if user specifies (default: full-time).
- listed_at: Default 2592000 (30 days). Use 604800 (7 days) if user wants fresh postings.

Call the create_linkedin_search tool with your final parameters."""

DEFAULT_CANDIDATE_CONTEXT = """\
## Candidate Background

**Level**: Mid-level AI Engineer (2+ years production experience)
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
**Model providers**: Claude (Bedrock), ChatGPT, Gemini
**Languages**: Python (primary), SQL, Java, C++, Bash
**Domain**: Regulated finance / reinsurance (RGA), actuarial systems, underwriting, compliance

**Education**: M.S. Computational Data Science, Carnegie Mellon University (GPA 3.85); \
B.S. Data Science, Duke Kunshan University (GPA 3.86)

## Market Positioning (Role Tiers)

**Tier 1 — Best fit** (prioritize these):
  Applied AI Engineer, GenAI Engineer, AI Engineer
  JD signals: LLM applications, RAG pipelines, agent systems, enterprise AI, evaluation pipelines
  Target companies: Databricks, Anthropic, Stripe, Snowflake, Adobe, Notion, Figma, Canva, \
AI infra startups, mid-to-large tech product teams

**Tier 2 — Also strong**:
  Machine Learning Engineer (applied, not training-heavy)
  JD signals: ML systems, feature pipelines, model deployment, inference optimization
  Avoid: training-heavy ML roles, large-scale pretraining, CUDA/kernel engineering

**Tier 3 — Possible but harder**:
  AI Platform Engineer (requires more infra/distributed systems depth)

**DO NOT target**:
- AI Research Scientist, Staff AI Engineer, Principal AI Engineer (wrong level / wrong track)
- Foundation model teams: OpenAI training, Anthropic research, DeepMind (research-heavy)
- Pure data science / analytics (no LLM/AI engineering component)
- Pure SWE with no ML/AI component
- Junior roles, research-only positions, hardware/chip-level ML

**Best company types**:
  Mid-to-large tech product companies: Snowflake, Databricks, Stripe, Adobe, Salesforce,
  Atlassian, Notion, Figma, Canva — they value applied AI and product integration over research
  Big tech product AI teams (not research): Google Workspace AI, Microsoft Copilot,
  Amazon AI apps, Meta AI product
"""

ANALYSIS_SYSTEM_PROMPT = """\
You are a precise job matching analyst evaluating roles for a specific candidate.

The candidate context below is the source of truth for their background and target positioning. \
Use it as the primary basis for scoring. Do not invent experience not supported by the context.

Candidate context:
{candidate_resume_text}

Current search request: "{query}"
Preferred company sizes: {sizes}

## Reasoning Process (internal — do not output)

Step 1: Re-read the candidate's market positioning from the context:
  - Target tier: Tier 1 = Applied AI / GenAI / AI Engineer; Tier 2 = Applied ML Engineer
  - Core strengths: production RAG, agentic pipelines, LLM orchestration, multimodal
  - Best company fit: mid-to-large tech product companies (Databricks, Stripe, Snowflake, etc.)
  - NOT targeting: research roles, Staff/Principal level, foundation model teams
Step 2: Score each job against that positioning — not just keyword overlap.
Step 3: Output ONLY the final JSON.

## Output Schema (JSON array, one object per job)

- job_id: string
- relevance_score: float 0.0–1.0
- relevance_explanation: 1–2 sentences specific to this candidate's background
- skills_match: list[string] — candidate's skills that directly satisfy job requirements
- skills_gap: list[string] — genuine gaps only; be conservative, do not list skills \
  the candidate likely has from context
- pros: list[string] — concrete reasons this role suits this specific candidate
- cons: list[string] — real concerns: visa risk, over/under-leveling, domain mismatch, \
  training-heavy vs applied, research vs product
- recommendation: "strong_match" | "good_match" | "weak_match" | "no_match"

## Scoring Guide

  0.9–1.0  Tier 1 role at a product company; core JD aligns directly with RAG / agentic / \
LLM engineering strengths; seniority matches mid-level
  0.75–0.89 Tier 1 or Tier 2 role with minor domain stretch or one soft gap
  0.6–0.74 Tier 2 role, or Tier 1 with meaningful gaps (training-heavy, infra-heavy, \
wrong level)
  0.4–0.59 Tier 3 role or Tier 1/2 at a research-focused company; candidate could apply \
but fit is marginal
  <0.4     Research role, wrong seniority, pure SWE, pure data science, or foundation \
model team — do not recommend

## Evaluation Rules

- Reward roles whose JD explicitly values production AI systems, RAG, agent frameworks, \
  LLM integration, or enterprise AI — even if terminology differs from the candidate's resume.
- Penalize roles that are primarily: ML research, pretraining, CUDA/kernel engineering, \
  data analytics without AI, or require 5+ years for a mid-level candidate.
- Score company-type fit as a signal: a strong Tier 1 JD at a pure research lab scores \
  lower than the same JD at a product company.
- Do not over-penalize skills gaps that are learnable on the job for a mid-level engineer.
- Do not reward a role just because it contains AI/ML buzzwords — score the actual \
  responsibilities.

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
        # Prefer parsed resume text; use the default context only when no resume exists.
        self.candidate_resume_text = candidate_profile or DEFAULT_CANDIDATE_CONTEXT

    @property
    def candidate_profile(self) -> str:
        """Backward-compatible alias for parsed resume text used by the analyzer."""
        return self.candidate_resume_text

    @candidate_profile.setter
    def candidate_profile(self, value: str) -> None:
        self.candidate_resume_text = value

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
            system=SEARCH_SYSTEM_PROMPT.format(
                candidate_resume_text=self.candidate_resume_text,
            ),
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
                "Extract LinkedIn job search parameters from the user's description, using "
                "the parsed resume text as the primary background context.\n\n"
                f"Resume text from resume parser:\n{self.candidate_resume_text}\n\n"
                "Return a JSON object with keys: keywords, location_name, and optionally "
                "remote, experience, job_type, listed_at. Keep keywords simple and aligned "
                "with roles the candidate is genuinely qualified for. Return ONLY valid JSON."
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
            candidate_resume_text=self.candidate_resume_text,
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
