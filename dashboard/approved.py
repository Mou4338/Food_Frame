"""Auto Approved page -- historical visibility only, NOT a review queue.
Score >= 80 items land here automatically and never appear in Human Review.

Approved images are uploaded straight to Google Drive and their local
temp copies are deleted immediately (see pipeline.py / storage_manager.py),
so this page shows the item name, the source it was approved from, and a
Drive link -- not a local thumbnail (except in the rare case Drive isn't
configured and images are still on local disk)."""
import os

import streamlit as st

from dashboard.style import status_badge

APPROVED_VIA = {
    "AUTO_APPROVED": "Auto-approved (score ≥ 80)",
    "HUMAN_APPROVED": "Approved by reviewer",
}


def render(db, cfg):
    st.title("✅ Auto Approved")
    st.caption("Items that were approved (automatically at score 80+, or by a reviewer) — nothing to action here. "
              "Images live on Google Drive; local copies were deleted once uploaded.")

    jobs = db.get_jobs(status=["AUTO_APPROVED", "HUMAN_APPROVED"], limit=500)
    st.write(f"**{len(jobs)}** approved item(s).")

    for job in jobs:
        with st.container(border=True):
            best = next((c for c in db.get_candidates(job["job_id"], attempt=1) if c["rank"] == 1), None)
            local_path = best.get("local_path") if best else None
            has_local_preview = bool(local_path and os.path.exists(local_path))

            cols = st.columns([1, 3]) if has_local_preview else [st.container()]
            if has_local_preview:
                with cols[0]:
                    st.image(local_path, width='stretch')
                info_col = cols[1]
            else:
                info_col = cols[0]

            with info_col:
                st.markdown(f"**{job['food_name']}**  {status_badge(job['status'])}", unsafe_allow_html=True)
                st.markdown(
                    f"**Approved from source:** {job.get('selected_source') or '—'}  \n"
                    f"**Approved via:** {APPROVED_VIA.get(job['status'], job['status'])}"
                )
                st.caption(f"Best score: {job.get('best_score')} · "
                          f"AI: {best.get('ai_score') if best else '—'} · Technical: {best.get('technical_score') if best else '—'}")
                if job.get("drive_link"):
                    st.write(f"📁 [Open image on Google Drive]({job['drive_link']})")
                else:
                    st.caption("No Drive link recorded for this item.")
                with st.expander("View full candidate comparison (audit)"):
                    for c in db.get_candidates(job["job_id"], attempt=1):
                        st.write(f"{c['source']}: {c.get('final_score', c['availability'])}")
