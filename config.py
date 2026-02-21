import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    linkedin_email: str
    linkedin_password: str
    anthropic_api_key: str
    gmail_address: str
    gmail_app_password: str
    gmail_recipient: str
    max_jobs_to_fetch: int
    max_jobs_to_email: int
    claude_model: str


def load_config() -> Config:
    """Load and validate configuration from .env file."""
    load_dotenv()

    required_vars = [
        "LINKEDIN_EMAIL",
        "LINKEDIN_PASSWORD",
        "ANTHROPIC_API_KEY",
        "GMAIL_ADDRESS",
        "GMAIL_APP_PASSWORD",
        "GMAIL_RECIPIENT",
    ]

    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    return Config(
        linkedin_email=os.environ["LINKEDIN_EMAIL"],
        linkedin_password=os.environ["LINKEDIN_PASSWORD"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        gmail_address=os.environ["GMAIL_ADDRESS"],
        gmail_app_password=os.environ["GMAIL_APP_PASSWORD"],
        gmail_recipient=os.environ["GMAIL_RECIPIENT"],
        max_jobs_to_fetch=int(os.getenv("MAX_JOBS_TO_FETCH", "50")),
        max_jobs_to_email=int(os.getenv("MAX_JOBS_TO_EMAIL", "10")),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
    )
