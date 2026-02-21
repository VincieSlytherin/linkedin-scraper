from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analyzer import JobAnalysis
    from scraper import JobListing

logger = logging.getLogger(__name__)

GMAIL_SMTP_SERVER = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


class EmailError(Exception):
    pass


class EmailSender:
    """Sends formatted job results via Gmail SMTP."""

    def __init__(self, gmail_address: str, gmail_app_password: str) -> None:
        self.gmail_address = gmail_address
        self.gmail_app_password = gmail_app_password

    def send_job_results(
        self,
        recipient: str,
        search_query: str,
        results: list[tuple[JobListing, JobAnalysis]],
    ) -> bool:
        """Send job results email. Returns True on success."""
        try:
            message = self._build_email(recipient, search_query, results)
            self._send_smtp(message)
            return True
        except Exception as exc:
            logger.error("Failed to send email: %s", exc)
            return False

    def _build_email(
        self,
        recipient: str,
        search_query: str,
        results: list[tuple[JobListing, JobAnalysis]],
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"LinkedIn Job Results: \"{search_query[:50]}\" ({len(results)} matches)"
        msg["From"] = self.gmail_address
        msg["To"] = recipient

        plain = self._format_plain_text(search_query, results)
        html = self._format_html(search_query, results)

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))
        return msg

    # -- plain text -----------------------------------------------------

    def _format_plain_text(
        self,
        search_query: str,
        results: list[tuple[JobListing, JobAnalysis]],
    ) -> str:
        lines = [
            "LinkedIn Job Search Results",
            f'Query: "{search_query}"',
            f"Matches: {len(results)}",
            "=" * 50,
        ]
        for i, (job, analysis) in enumerate(results, 1):
            lines.append(f"\n[{i}] {job.title}")
            lines.append(f"    Company:  {job.company.name} ({job.company.size_category})")
            lines.append(f"    Location: {job.location}{' (Remote)' if job.remote_allowed else ''}")
            lines.append(f"    Score:    {analysis.relevance_score:.0%} — {analysis.recommendation}")
            if analysis.skills_match:
                lines.append(f"    Skills:   {', '.join(analysis.skills_match[:5])}")
            if analysis.skills_gap:
                lines.append(f"    Gap:      {', '.join(analysis.skills_gap[:3])}")
            lines.append(f"    Link:     {job.url}")
            lines.append(f"    Why:      {analysis.relevance_explanation}")
            if job.description:
                lines.append(f"    Desc:     {job.description[:300]}...")
        lines.append("\n" + "=" * 50)
        return "\n".join(lines)

    # -- HTML -----------------------------------------------------------

    def _format_html(
        self,
        search_query: str,
        results: list[tuple[JobListing, JobAnalysis]],
    ) -> str:
        cards = []
        for i, (job, analysis) in enumerate(results, 1):
            score_pct = int(analysis.relevance_score * 100)
            bar_color = (
                "#22c55e" if score_pct >= 80
                else "#eab308" if score_pct >= 60
                else "#ef4444"
            )
            skills_html = ""
            if analysis.skills_match:
                badges = "".join(
                    f'<span style="display:inline-block;background:#dbeafe;color:#1e40af;'
                    f'padding:2px 8px;border-radius:12px;font-size:12px;margin:2px;">'
                    f'{s}</span>'
                    for s in analysis.skills_match[:6]
                )
                skills_html = f'<div style="margin-top:8px;">Skills match: {badges}</div>'

            gap_html = ""
            if analysis.skills_gap:
                gap_badges = "".join(
                    f'<span style="display:inline-block;background:#fee2e2;color:#991b1b;'
                    f'padding:2px 8px;border-radius:12px;font-size:12px;margin:2px;">'
                    f'{s}</span>'
                    for s in analysis.skills_gap[:4]
                )
                gap_html = f'<div style="margin-top:4px;">Skills gap: {gap_badges}</div>'

            pros_html = ""
            if analysis.pros:
                items = "".join(f"<li>{p}</li>" for p in analysis.pros[:3])
                pros_html = f'<div style="margin-top:6px;color:#166534;font-size:13px;">Pros:<ul style="margin:2px 0;">{items}</ul></div>'

            cons_html = ""
            if analysis.cons:
                items = "".join(f"<li>{c}</li>" for c in analysis.cons[:3])
                cons_html = f'<div style="margin-top:4px;color:#991b1b;font-size:13px;">Cons:<ul style="margin:2px 0;">{items}</ul></div>'

            desc_preview = job.description[:500].replace("\n", " ") if job.description else ""

            cards.append(f"""
            <div style="border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:16px;background:#fff;">
                <div style="display:flex;justify-content:space-between;align-items:start;">
                    <div>
                        <h2 style="margin:0;font-size:18px;">
                            <a href="{job.url}" style="color:#1d4ed8;text-decoration:none;">
                                [{i}] {job.title}
                            </a>
                        </h2>
                        <p style="margin:4px 0 0;color:#6b7280;font-size:14px;">
                            {job.company.name}
                            <span style="background:#f3f4f6;padding:1px 6px;border-radius:4px;font-size:12px;margin-left:4px;">
                                {job.company.size_category or 'unknown'}
                            </span>
                            &nbsp;|&nbsp; {job.location}
                            {'&nbsp; 🏠 Remote' if job.remote_allowed else ''}
                        </p>
                    </div>
                    <div style="text-align:right;min-width:80px;">
                        <div style="font-size:24px;font-weight:bold;color:{bar_color};">{score_pct}%</div>
                        <div style="font-size:11px;color:#6b7280;">{analysis.recommendation.replace('_', ' ')}</div>
                    </div>
                </div>
                <div style="margin-top:8px;background:#f3f4f6;border-radius:4px;height:6px;overflow:hidden;">
                    <div style="background:{bar_color};height:100%;width:{score_pct}%;border-radius:4px;"></div>
                </div>
                <p style="margin:10px 0 0;font-size:13px;color:#374151;">{analysis.relevance_explanation}</p>
                {skills_html}
                {gap_html}
                {pros_html}
                {cons_html}
                <details style="margin-top:10px;">
                    <summary style="cursor:pointer;color:#6b7280;font-size:13px;">Job description preview</summary>
                    <p style="font-size:12px;color:#4b5563;margin-top:4px;white-space:pre-wrap;">{desc_preview}...</p>
                </details>
                <div style="margin-top:10px;">
                    <a href="{job.url}" style="display:inline-block;background:#1d4ed8;color:#fff;padding:6px 16px;border-radius:6px;text-decoration:none;font-size:13px;">
                        View on LinkedIn
                    </a>
                </div>
            </div>""")

        return f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f9fafb;padding:20px;margin:0;">
    <div style="max-width:680px;margin:0 auto;">
        <div style="background:#1e3a5f;color:#fff;padding:20px;border-radius:8px 8px 0 0;">
            <h1 style="margin:0;font-size:22px;">LinkedIn Job Search Results</h1>
            <p style="margin:6px 0 0;opacity:0.85;font-size:14px;">Query: "{search_query}"</p>
            <p style="margin:4px 0 0;opacity:0.7;font-size:13px;">{len(results)} matching jobs found</p>
        </div>
        <div style="padding:16px;background:#fff;border-radius:0 0 8px 8px;border:1px solid #e5e7eb;border-top:none;">
            {''.join(cards)}
        </div>
        <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
            Powered by LinkedIn Job Scraper + Claude AI
        </p>
    </div>
</body>
</html>"""

    # -- SMTP -----------------------------------------------------------

    def _send_smtp(self, message: MIMEMultipart) -> None:
        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(self.gmail_address, self.gmail_app_password)
            server.send_message(message)
        logger.info("Email sent to %s", message["To"])
