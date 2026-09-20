"""Errors / Failed Jobs page -- technical failures kept separate from
low-quality-image rejections: API timeouts, download failures, AI
evaluation failures, processing/upload/auth failures. Never shown with a
passing score."""
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
    st.title("⚠️ Errors / Failed Jobs")
    st.caption("Technical failures — never converted into a passing score. Retry, change provider, or upload manually.")

    error_jobs = db.get_jobs(status="ERROR", limit=500)
    not_found_jobs = db.get_jobs(status="NOT_FOUND", limit=500)
    all_jobs = error_jobs + not_found_jobs

    error_types = sorted({j.get("error_type") for j in error_jobs if j.get("error_type")})
    type_filter = st.selectbox("Filter by error type", ["All"] + error_types)
    if type_filter != "All":
        all_jobs = [j for j in all_jobs if j.get("error_type") == type_filter]

    st.write(f"**{len(all_jobs)}** failed job(s).")
    secrets = Secrets()

    if all_jobs and st.button("🔄 Retry All"):
        try:
            uploader = _get_uploader(cfg, secrets)
            rejected_uploader = _get_rejected_uploader(cfg, secrets)
        except RuntimeError as e:
            st.error(f"Could not upload to Google Drive: {e}")
        else:
            with st.spinner(f"Retrying {len(all_jobs)} item(s)..."):
                for job in all_jobs:
                    search_again(job, cfg, secrets, db, uploader=uploader, sanitize_filename=sanitize_filename,
                                rejected_uploader=rejected_uploader)
            st.rerun()

    for job in all_jobs:
        with st.container(border=True):
            st.markdown(f"**{job['food_name']}**  {status_badge(job['status'])}", unsafe_allow_html=True)
            st.caption(f"Error type: {job.get('error_type') or 'search/no candidates'} · "
                      f"{job.get('error_message') or 'No usable candidate from any enabled source'}")

            col1, col2, col3, col4 = st.columns(4)
            if col1.button("🔄 Retry", key=f"retry_{job['job_id']}"):
                with st.spinner("Retrying..."):
                    try:
                        search_again(job, cfg, secrets, db, uploader=_get_uploader(cfg, secrets),
                                    sanitize_filename=sanitize_filename,
                                    rejected_uploader=_get_rejected_uploader(cfg, secrets))
                    except RuntimeError as e:
                        st.error(f"Could not upload to Google Drive: {e}")
                st.rerun()

            with col2.popover("📤 Manual Upload"):
                uploaded = st.file_uploader("Upload replacement image", type=["jpg", "jpeg", "png"],
                                            key=f"err_manual_{job['job_id']}")
                if uploaded and st.button("Use this image", key=f"err_manual_confirm_{job['job_id']}"):
                    from PIL import Image
                    img = Image.open(uploaded).convert("RGB")
                    tmp_path = f"{secrets.TEMP_IMAGE_DIR}/manual_err_{job['job_id']}.jpg"
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

            if col3.button("✔ Mark Resolved", key=f"resolve_{job['job_id']}"):
                db.update_job(job["job_id"], status="REJECTED", rejection_reason="Marked resolved without image")
                db.log_action(job["job_id"], "worker", "Mark Resolved")
                st.rerun()

            with col4.expander("Details"):
                for c in db.get_candidates(job["job_id"]):
                    st.write(f"Attempt {c['attempt']} · {c['source']}: {c['availability']} — {c.get('reason','')}")
