"""Rejected page -- items below 65, or human-rejected, with Search Again
and Manual Upload recovery options."""
import re

import streamlit as st

import storage_manager
from config import Secrets
from fetched_log import record_fetched
from dashboard.style import status_badge
from pipeline import finalize_and_store
from retry_manager import search_again


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip().rstrip(".") or "unnamed_item"


def _get_uploader(cfg, secrets):
    return storage_manager.get_uploader(cfg, secrets, kind="approved")


def _get_rejected_uploader(cfg, secrets):
    return storage_manager.get_uploader(cfg, secrets, kind="rejected")


def render(db, cfg):
    st.title("🚫 Rejected")
    st.caption("Best score below 65, or rejected by a reviewer. Recoverable via Search Again or Manual Upload.")

    reason_filter = st.selectbox("Filter by reason", ["All"] + [
        "Wrong food", "Poor quality", "Poor composition", "Watermark/logo",
        "Unsuitable menu image", "Duplicate", "Licensing concern", "Other",
    ])
    jobs = db.get_jobs(status="REJECTED", limit=500)
    if reason_filter != "All":
        jobs = [j for j in jobs if j.get("rejection_reason") == reason_filter]

    st.write(f"**{len(jobs)}** rejected item(s).")
    secrets = Secrets()

    for job in jobs:
        with st.container(border=True):
            st.markdown(f"**{job['food_name']}**  {status_badge(job['status'])}", unsafe_allow_html=True)
            st.caption(f"Best score: {job.get('best_score')} · Winning source (attempt 1): {job.get('selected_source') or '—'} "
                      f"· Reason: {job.get('rejection_reason') or 'low score'} · Retries: {job.get('retry_count') or 0}")
            if job.get("drive_link"):
                st.caption(f"📁 Audit copy on Google Drive (not kept locally): [Open image]({job['drive_link']})")

            with st.expander("All candidate scores"):
                candidates = db.get_candidates(job["job_id"])
                for c in candidates:
                    st.write(f"Attempt {c['attempt']} · {c['source']}: "
                            f"{c.get('final_score', c['availability'])} — {c.get('reason','')}")

            col1, col2, col3 = st.columns(3)
            if col1.button("🔄 Search Again", key=f"rej_search_{job['job_id']}"):
                with st.spinner("Searching again..."):
                    try:
                        search_again(job, cfg, secrets, db, uploader=_get_uploader(cfg, secrets),
                                    sanitize_filename=sanitize_filename,
                                    rejected_uploader=_get_rejected_uploader(cfg, secrets))
                    except RuntimeError as e:
                        st.error(f"Could not upload to Google Drive: {e}")
                st.rerun()

            with col2.popover("📤 Manual Upload"):
                uploaded = st.file_uploader("Upload a replacement image", type=["jpg", "jpeg", "png"],
                                            key=f"manual_{job['job_id']}")
                if uploaded and st.button("Use this image", key=f"manual_confirm_{job['job_id']}"):
                    from PIL import Image
                    import io
                    img = Image.open(uploaded).convert("RGB")
                    tmp_path = f"{secrets.TEMP_IMAGE_DIR}/manual_{job['job_id']}.jpg"
                    img.save(tmp_path, format="JPEG", quality=92)
                    try:
                        uploader = _get_uploader(cfg, secrets)
                        drive_link, filename, err = finalize_and_store(
                            job["food_name"], {"local_path": tmp_path}, cfg, uploader, sanitize_filename
                        )
                    except RuntimeError as e:
                        st.error(f"Could not upload to Google Drive: {e}")
                        drive_link, err = None, str(e)
                    storage_manager.delete_local_files([tmp_path])  # uploaded (or unrecoverable) -> don't keep it
                    if err:
                        if "Could not upload to Google Drive" not in str(err):
                            st.error(err)
                    else:
                        db.update_job(job["job_id"], status="HUMAN_APPROVED", drive_link=drive_link,
                                     selected_source="Manual Upload", reviewer="worker")
                        db.log_action(job["job_id"], "worker", "Manual Upload")
                        record_fetched(secrets.FETCHED_LOG_PATH, job["food_name"], drive_link, "Manual Upload")
                        st.success("Manually uploaded and approved. Local copy removed.")
                        st.rerun()

            col3.caption(f"Attempted sources: {', '.join(sorted({c['source'] for c in db.get_candidates(job['job_id'])}))}")
