"""dashboard.py — Streamlit dashboard for tracking job applications.

Run with: streamlit run dashboard.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from database import JobDatabase, DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Job Tracker",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Shared DB connection (cached per session)
# ---------------------------------------------------------------------------

@st.cache_resource
def get_db() -> JobDatabase:
    return JobDatabase(db_path=DEFAULT_DB_PATH)


db = get_db()


def _fmt_time(ts: float | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y")


STATUS_EMOJI = {
    "recommended":  "📬",
    "applied":      "📤",
    "phone_screen": "📞",
    "interview":    "🗓️",
    "offer":        "🎉",
    "rejected":     "❌",
    "withdrawn":    "↩️",
    "not_interested": "🚫",
}

STATUS_COLOR = {
    "recommended":  "#6c757d",
    "applied":      "#0d6efd",
    "phone_screen": "#fd7e14",
    "interview":    "#6f42c1",
    "offer":        "#198754",
    "rejected":     "#dc3545",
    "withdrawn":    "#adb5bd",
    "not_interested": "#adb5bd",
}

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_jobs, tab_resume, tab_stats = st.tabs(["💼 Jobs", "📄 Resume", "📊 Stats"])


# ===========================================================================
# TAB 1 — JOBS
# ===========================================================================

with tab_jobs:
    st.header("Job Applications")

    jobs = db.get_dashboard_jobs()

    if not jobs:
        st.info("No recommended jobs yet. Run `python main.py` to search for jobs.")
        st.stop()

    df = pd.DataFrame(jobs)

    # ── Filters ──────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
    with col_f1:
        status_filter = st.multiselect(
            "Filter by status",
            options=list(STATUS_EMOJI.keys()),
            default=list(STATUS_EMOJI.keys()),
            format_func=lambda s: f"{STATUS_EMOJI[s]} {s.replace('_', ' ').title()}",
        )
    with col_f2:
        min_score = st.slider("Min relevance score", 0.0, 1.0, 0.0, 0.05)
    with col_f3:
        search_text = st.text_input("Search title / company", "")

    # Apply filters
    mask = df["status"].isin(status_filter)
    if min_score > 0:
        mask &= df["relevance_score"].fillna(0) >= min_score
    if search_text:
        q = search_text.lower()
        mask &= (
            df["title"].str.lower().str.contains(q, na=False)
            | df["company_name"].str.lower().str.contains(q, na=False)
        )
    df_view = df[mask].reset_index(drop=True)

    st.caption(f"Showing {len(df_view)} of {len(df)} jobs")

    # ── Job cards ─────────────────────────────────────────────────────────────
    for _, row in df_view.iterrows():
        job_id = row["job_id"]
        score = row.get("relevance_score") or 0.0
        status = row.get("status", "recommended")
        rec = row.get("recommendation") or "—"
        skills_match = json.loads(row["skills_match"]) if row.get("skills_match") else []
        skills_gap = json.loads(row["skills_gap"]) if row.get("skills_gap") else []

        with st.expander(
            f"{STATUS_EMOJI.get(status, '•')}  **{row['title']}** @ {row['company_name']}  "
            f"·  {score:.0%}  ·  {row.get('location', '—')}",
            expanded=False,
        ):
            left, right = st.columns([3, 2])

            with left:
                # Score bar
                bar = int(score * 20)
                st.markdown(
                    f"`[{'█' * bar}{'░' * (20 - bar)}]` **{score:.0%}** · {rec.replace('_', ' ').title()}"
                )
                if row.get("relevance_explanation"):
                    st.caption(row["relevance_explanation"])

                # Skills
                if skills_match:
                    st.markdown(
                        "**Match:** " + " ".join(
                            f'<span style="background:#d1fae5;color:#065f46;'
                            f'padding:2px 7px;border-radius:12px;font-size:0.8em">{s}</span>'
                            for s in skills_match
                        ),
                        unsafe_allow_html=True,
                    )
                if skills_gap:
                    st.markdown(
                        "**Gap:** " + " ".join(
                            f'<span style="background:#fee2e2;color:#991b1b;'
                            f'padding:2px 7px;border-radius:12px;font-size:0.8em">{s}</span>'
                            for s in skills_gap
                        ),
                        unsafe_allow_html=True,
                    )

                # Meta
                remote_badge = " 🏠 Remote" if row.get("remote_allowed") else ""
                sent_ts = _fmt_time(row.get("sent_at"))
                st.caption(
                    f"{row.get('company_size_category', '').title()} company · "
                    f"Recommended {sent_ts}{remote_badge}"
                )
                st.markdown(f"[View on LinkedIn ↗]({row['url']})")

            with right:
                # Editable status
                new_status = st.selectbox(
                    "Status",
                    options=list(STATUS_EMOJI.keys()),
                    index=list(STATUS_EMOJI.keys()).index(status),
                    format_func=lambda s: f"{STATUS_EMOJI[s]} {s.replace('_', ' ').title()}",
                    key=f"status_{job_id}",
                )

                # Notes
                current_notes = row.get("notes") or ""
                new_notes = st.text_area(
                    "Notes",
                    value=current_notes,
                    height=80,
                    placeholder="Recruiter contact, interview prep, next steps...",
                    key=f"notes_{job_id}",
                )

                # Save button
                if st.button("Save", key=f"save_{job_id}"):
                    db.upsert_application(job_id, new_status, new_notes)
                    st.success("Saved!")
                    st.rerun()

                if row.get("applied_at"):
                    st.caption(f"Applied: {_fmt_time(row['applied_at'])}")
                if row.get("updated_at") and row["updated_at"] != row.get("applied_at"):
                    st.caption(f"Updated: {_fmt_time(row['updated_at'])}")


# ===========================================================================
# TAB 2 — RESUME
# ===========================================================================

with tab_resume:
    st.header("Resume")

    col_upload, col_current = st.columns([1, 1])

    with col_upload:
        st.subheader("Upload Resume")
        uploaded = st.file_uploader(
            "PDF, DOCX, TXT, or Typst (.typ)",
            type=["pdf", "docx", "doc", "txt", "md", "typ"],
        )

        if uploaded is not None:
            if st.button("Parse & Save Resume", type="primary"):
                with st.spinner("Parsing resume..."):
                    try:
                        from resume_parser import parse_resume_bytes
                        raw_text = parse_resume_bytes(uploaded.name, uploaded.read())
                        resume_id = db.save_resume(uploaded.name, raw_text)
                        st.success(f"Saved **{uploaded.name}** ({len(raw_text):,} characters)")
                        st.info(
                            "Run `python main.py` and the profile will be auto-extracted "
                            "on the next job search. Or click 'Extract Profile' below."
                        )
                        st.session_state["new_resume_id"] = resume_id
                        st.session_state["new_resume_text"] = raw_text
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed to parse: {exc}")

    with col_current:
        resume = db.get_latest_resume()
        if resume:
            st.subheader(f"Current: {resume['filename']}")
            st.caption(f"Uploaded {_fmt_time(resume['uploaded_at'])}")
        else:
            st.subheader("No resume uploaded yet")

    # Profile section
    st.divider()
    st.subheader("Extracted Candidate Profile")

    resume = db.get_latest_resume()
    if resume is None:
        st.info("Upload a resume above to get a Claude-generated profile for job matching.")
    else:
        col_profile, col_btn = st.columns([4, 1])
        with col_btn:
            if st.button("Re-extract Profile", help="Use Claude to re-generate the profile from your resume"):
                with st.spinner("Extracting profile with Claude..."):
                    try:
                        from config import load_config
                        from analyzer import JobAnalyzer
                        cfg = load_config()
                        tmp_analyzer = JobAnalyzer(api_key=cfg.anthropic_api_key, model=cfg.claude_model)
                        profile = tmp_analyzer.extract_profile_from_resume(resume["raw_text"])
                        db.update_resume_profile(resume["id"], profile)
                        st.success("Profile updated!")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Failed: {exc}")

        with col_profile:
            if resume.get("extracted_profile"):
                st.markdown(resume["extracted_profile"])
            else:
                st.info(
                    "Profile not extracted yet. Click **Re-extract Profile** or run `python main.py`."
                )

        with st.expander("View raw resume text"):
            st.text(resume["raw_text"][:5000] + ("…" if len(resume["raw_text"]) > 5000 else ""))


# ===========================================================================
# TAB 3 — STATS
# ===========================================================================

with tab_stats:
    st.header("Stats")

    jobs = db.get_dashboard_jobs()
    if not jobs:
        st.info("No data yet. Run `python main.py` to get started.")
        st.stop()

    df_all = pd.DataFrame(jobs)

    # ── KPI row ──────────────────────────────────────────────────────────────
    total = len(df_all)
    applied = (df_all["status"].isin(["applied", "phone_screen", "interview", "offer", "rejected"])).sum()
    active = (df_all["status"].isin(["phone_screen", "interview", "offer"])).sum()
    offers = (df_all["status"] == "offer").sum()
    avg_score = df_all["relevance_score"].dropna().mean()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Recommended", total)
    k2.metric("Applied", int(applied))
    k3.metric("Active Pipeline", int(active))
    k4.metric("Offers", int(offers))
    k5.metric("Avg Score", f"{avg_score:.0%}" if not pd.isna(avg_score) else "—")

    st.divider()

    col_chart1, col_chart2 = st.columns(2)

    # ── Status breakdown ──────────────────────────────────────────────────────
    with col_chart1:
        st.subheader("Applications by Status")
        status_counts = df_all["status"].value_counts().reset_index()
        status_counts.columns = ["status", "count"]
        status_counts["label"] = status_counts["status"].apply(
            lambda s: f"{STATUS_EMOJI.get(s, '')} {s.replace('_', ' ').title()}"
        )
        st.bar_chart(status_counts.set_index("label")["count"])

    # ── Score distribution ────────────────────────────────────────────────────
    with col_chart2:
        st.subheader("Relevance Score Distribution")
        scored = df_all["relevance_score"].dropna()
        if len(scored) > 0:
            bins = pd.cut(scored, bins=[0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01],
                          labels=["<50%", "50–60%", "60–70%", "70–80%", "80–90%", "90–100%"])
            st.bar_chart(bins.value_counts().sort_index())
        else:
            st.info("No scored jobs yet.")

    # ── Application funnel ────────────────────────────────────────────────────
    st.subheader("Application Funnel")
    funnel_stages = ["recommended", "applied", "phone_screen", "interview", "offer"]
    funnel_data = {
        stage: int((df_all["status"] == stage).sum()) +
               (int((df_all["status"].isin(["phone_screen", "interview", "offer", "rejected", "withdrawn"])).sum())
                if stage == "applied" else 0)
        for stage in funnel_stages
    }
    # Cumulative: each stage includes all downstream
    cumulative = {}
    running = 0
    for stage in reversed(funnel_stages):
        running += funnel_data.get(stage, 0)
        cumulative[stage] = running
    funnel_df = pd.DataFrame(
        [(s.replace("_", " ").title(), cumulative[s]) for s in funnel_stages],
        columns=["Stage", "Count"],
    )
    st.dataframe(funnel_df, use_container_width=True, hide_index=True)

    # ── Timeline ─────────────────────────────────────────────────────────────
    st.subheader("Recommended Over Time")
    df_all["sent_date"] = pd.to_datetime(df_all["sent_at"], unit="s").dt.date
    timeline = df_all.groupby("sent_date").size().reset_index(name="jobs")
    if len(timeline) > 0:
        st.line_chart(timeline.set_index("sent_date")["jobs"])


