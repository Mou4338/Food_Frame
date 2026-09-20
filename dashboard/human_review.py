"""Human Review page -- the core worker screen. Shows only jobs scored
65-79.99 (already filtered before this page is reached), with the full
five-source comparison, AI explainability, and Approve / Reject /
Search Again / Select Another actions.
"""
import os
import re

import streamlit as st

import decision_engine
import storage_manager
from config import Secrets
from dashboard.style import status_badge
from fetched_log import record_fetched
from pipeline import finalize_and_store
from retry_manager import search_again

REJECTION_REASONS = [
    "Wrong food", "Poor quality", "Poor composition", "Watermark/logo",
    "Unsuitable menu image", "Duplicate", "Licensing concern", "Other",
]


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip().rstrip(".") or "unnamed_item"


def _get_uploader(cfg, secrets):
    return storage_manager.get_uploader(cfg, secrets, kind="approved")


def _get_rejected_uploader(cfg, secrets):
    return storage_manager.get_uploader(cfg, secrets, kind="rejected")


def _render_candidate_card(c, is_winner: bool):
    with st.container(border=True):
        if c["availability"] not in ("EVALUATED",) or not c.get("local_path") or not os.path.exists(c.get("local_path") or ""):
            st.markdown(f"**{c['source']}**")
            st.caption("No candidate found" if c["availability"] in ("SOURCE_NO_RESULT",) else c["availability"])
            return
        st.image(c["local_path"], width='stretch')
        title = f"**{c['source']}**" + (" 🏆 AI Selected" if is_winner else "")
        st.markdown(title)
        st.caption(f"Final score: **{c.get('final_score', '—')}**")
        st.caption(f"AI: {c.get('ai_score','—')} · Technical: {c.get('technical_score','—')} · "
                  f"Composition: {c.get('composition_score','—')} · Color: {c.get('color_quality_score','—')}")
        if c.get("width"):
            st.caption(f"{c['width']}×{c['height']}px · {round(c.get('file_size_kb') or 0)}KB")
        if c.get("license"):
            st.caption(f"License: {c['license']} · {c.get('author','')}")


def render(db, cfg):
    st.title("🔍 Human Review")
    st.caption("Only items whose best-of-five score is 65–79.99 appear here. 80+ is auto-approved; below 65 is rejected.")
    top_n = (cfg.get("review", {}) or {}).get("top_n", 3)
    st.caption(f"Only the best {top_n} candidate(s) are kept and shown per item — the rest are scored, "
               "logged for audit, and their local copies deleted right away to save space.")

    jobs = db.get_jobs(status="HUMAN_REVIEW", limit=500)

    with st.expander("Filters"):
        name_filter = st.text_input("Food name contains")
        score_min, score_max = st.slider("Best-score range", 0, 100, (65, 80))
    if name_filter:
        jobs = [j for j in jobs if name_filter.lower() in j["food_name"].lower()]
    jobs = [j for j in jobs if j.get("best_score") is not None and score_min <= j["best_score"] <= score_max]

    st.write(f"**{len(jobs)}** item(s) waiting for review.")
    if not jobs:
        st.success("Nothing to review right now.")
        return

    secrets = Secrets()
    for job in jobs:
        with st.container():
            st.markdown(f"### {job['food_name']}  {status_badge(job['status'])}", unsafe_allow_html=True)
            st.caption(f"Normalized: `{job['normalized_name']}` · Category: {job.get('category') or '—'} · "
                      f"Best score: **{job.get('best_score')}** · Retries: {job.get('retry_count') or 0}")

            candidates = db.get_candidates(job["job_id"], attempt=None)
            latest_attempt = max((c["attempt"] for c in candidates), default=1)
            all_latest = [c for c in candidates if c["attempt"] == latest_attempt]
            all_latest.sort(key=lambda c: (c["rank"] is None, c["rank"] or 99))

            # Only the best `top_n` scored candidates are ever kept on disk
            # (see pipeline.py / retry_manager.py) and shown here.
            latest = [c for c in all_latest if c.get("rank") and c["rank"] <= top_n][:top_n]
            if not latest:
                latest = all_latest[:top_n]

            cols = st.columns(max(len(latest), 1))
            selected_source_key = f"select_{job['job_id']}"
            default_winner = next((c["source"] for c in latest if c.get("rank") == 1), None)
            for i, c in enumerate(latest):
                with cols[i % len(cols)]:
                    _render_candidate_card(c, is_winner=(c["source"] == default_winner))

            chosen_source = st.radio(
                "Select the candidate to approve", options=[c["source"] for c in latest],
                index=[c["source"] for c in latest].index(default_winner) if default_winner in [c["source"] for c in latest] else 0,
                horizontal=True, key=selected_source_key,
            )

            b1, b2, b3, b4 = st.columns(4)
            if b1.button("✅ Approve", key=f"approve_{job['job_id']}", type="primary"):
                chosen = next(c for c in latest if c["source"] == chosen_source)
                chosen_dict = {"local_path": chosen["local_path"]}
                try:
                    uploader = _get_uploader(cfg, secrets)
                    drive_link, filename, err = finalize_and_store(job["food_name"], chosen_dict, cfg, uploader, sanitize_filename)
                except RuntimeError as e:
                    st.error(f"Could not upload to Google Drive: {e}")
                    err = str(e)
                    drive_link = None
                if err:
                    db.update_job(job["job_id"], status=decision_engine.ERROR, error_type="PROCESSING_OR_UPLOAD",
                                 error_message=err)
                    if "Could not upload to Google Drive" not in str(err):
                        st.error(f"Approve failed: {err}")
                else:
                    db.update_job(job["job_id"], status=decision_engine.HUMAN_APPROVED, drive_link=drive_link,
                                 selected_source=chosen_source, reviewer="worker")
                    db.log_action(job["job_id"], "worker", "Approve", new_score=job.get("best_score"))
                    record_fetched(secrets.FETCHED_LOG_PATH, job["food_name"], drive_link, chosen_source)
                # Uploaded (or unrecoverable) -> delete every local copy kept for this item.
                storage_manager.cleanup_job_files(all_latest)
                if not err:
                    st.success("Approved and uploaded to Google Drive. Local copies removed.")
                    st.rerun()

            with b2.popover("❌ Reject"):
                reason = st.selectbox("Reason", REJECTION_REASONS, key=f"reason_{job['job_id']}")
                if st.button("Confirm reject", key=f"confirm_reject_{job['job_id']}"):
                    chosen = next((c for c in latest if c["source"] == chosen_source), latest[0])
                    try:
                        rejected_uploader = _get_rejected_uploader(cfg, secrets)
                        rej_sanitize = storage_manager.wrap_sanitize_for_rejected(sanitize_filename, cfg)
                        r_link, _r_filename, r_err = finalize_and_store(
                            job["food_name"], {"local_path": chosen["local_path"]}, cfg, rejected_uploader, rej_sanitize
                        )
                    except RuntimeError as e:
                        st.error(f"Could not upload rejected-item audit copy to Google Drive: {e}")
                        r_link, r_err = None, str(e)
                    db.update_job(job["job_id"], status=decision_engine.REJECTED, rejection_reason=reason,
                                 reviewer="worker", drive_link=(r_link if not r_err else None))
                    db.log_action(job["job_id"], "worker", "Reject", reason=reason, old_score=job.get("best_score"))
                    # Recorded on Drive (or unrecoverable) -> delete every local copy kept for this item.
                    storage_manager.cleanup_job_files(all_latest)
                    st.rerun()

            if b3.button("🔄 Search Again", key=f"search_again_{job['job_id']}"):
                with st.spinner("Searching all five sources again..."):
                    try:
                        search_again(job, cfg, secrets, db, uploader=_get_uploader(cfg, secrets),
                                    sanitize_filename=sanitize_filename,
                                    rejected_uploader=_get_rejected_uploader(cfg, secrets))
                    except RuntimeError as e:
                        st.error(f"Could not upload to Google Drive: {e}")
                st.rerun()

            b4.caption("Select Another = pick a different radio option above, then Approve.")
            st.divider()
