"""Overview page -- live run summary, KPIs, progress, health, and a
"Start a new run" panel to kick off batch processing as a background
process (so this page stays responsive and just polls the database)."""
import os
import subprocess
import sys
import tempfile
import time

import streamlit as st

import report_generator
from config import Secrets
from dashboard.style import kpi_card, status_badge


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _start_run(excel_bytes, sheet_name, food_col, category_col):
    tmpdir = tempfile.mkdtemp()
    excel_path = os.path.join(tmpdir, "menu.xlsx")
    with open(excel_path, "wb") as f:
        f.write(excel_bytes)
    run_batch_path = os.path.join(PROJECT_ROOT, "run_batch.py")
    cmd = [sys.executable, run_batch_path, excel_path, "--sheet", sheet_name, "--column", food_col]
    if category_col:
        cmd += ["--category-column", category_col]
    log_path = os.path.join(tmpdir, "run.log")
    with open(log_path, "w") as logf:
        # cwd=PROJECT_ROOT so config.yaml / .env / the database path resolve
        # the same way no matter which folder `streamlit run` was launched
        # from.
        subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, cwd=PROJECT_ROOT)
    st.session_state["last_run_log"] = log_path


def _render_log_expander(log_path, live: bool):
    def _body():
        with st.expander("🪵 View last run's log (useful if a run doesn't seem to start)", expanded=live):
            with open(log_path, "r", errors="replace") as f:
                log_text = f.read().strip()
            st.code(log_text[-4000:] if log_text else "(log is empty so far — refresh in a moment)",
                    language="text")
    if live:
        st.fragment(run_every=2)(_body)()
    else:
        _body()


def _poll_for_first_run(db):
    """Shown right after 'Start automation run' is clicked, before its row
    has appeared in the database yet -- keeps checking every couple of
    seconds (without freezing the page) instead of just saying 'No runs
    yet' and requiring a manual browser refresh to notice it's ready."""
    @st.fragment(run_every=2)
    def _check():
        if db.get_runs(limit=1):
            st.rerun(scope="app")
        else:
            st.info("⏳ Starting your run... this updates automatically, no need to refresh the page.")
    _check()


def render(db, cfg):
    st.title("🍽️ Food Image Automation — Overview")

    with st.expander("▶ Start a new run", expanded=not db.get_runs(limit=1)):
        st.caption(
            "Upload your menu Excel file. Processing runs in the background — "
            "this page (and Human Review / Rejected / Errors) update live from the database."
        )
        col1, col2, col3 = st.columns(3)
        food_col = col1.text_input("Food name column", value=Secrets.FOOD_NAME_COLUMN)
        sheet_name = col2.text_input("Sheet name", value=Secrets.SHEET_NAME)
        category_col = col3.text_input("Category column (optional)", value="")
        excel_upload = st.file_uploader("Menu Excel file (.xlsx)", type=["xlsx"])
        if st.button("▶ Start automation run", type="primary", disabled=not excel_upload):
            _start_run(excel_upload.getbuffer(), sheet_name, food_col, category_col or None)
            st.session_state["awaiting_run"] = True
            st.success("Run started in the background. This page will update on its own once it appears below.")

        log_path = st.session_state.get("last_run_log")
        if log_path and os.path.exists(log_path):
            _render_log_expander(log_path, live=st.session_state.get("awaiting_run", False))

    runs = db.get_runs(limit=10)
    if not runs:
        if st.session_state.get("awaiting_run"):
            _poll_for_first_run(db)
        else:
            st.info("No runs yet — upload a menu file above to start your first run.")
        return

    st.session_state["awaiting_run"] = False

    current_run = runs[0]
    run_id = current_run["run_id"]

    if current_run["status"] == "running":
        auto_refresh = st.toggle("Auto-refresh every 3s", value=True)
    else:
        auto_refresh = False

    # A fragment re-runs on its own timer WITHOUT re-running (or blocking)
    # the rest of the page -- unlike the old time.sleep(3) + st.rerun()
    # pattern, which froze the whole dashboard for 3 seconds on every tick.
    body = st.fragment(run_every=3)(_render_live_run_body) if auto_refresh else _render_live_run_body
    body(db, cfg, current_run, run_id)


def _render_live_run_body(db, cfg, current_run, run_id):
    if current_run["status"] == "error":
        st.error(f"This run failed to complete: {current_run.get('current_stage') or 'unknown error'}")
        st.caption("Fix the issue above, then start a new run from the panel at the top of this page.")

    pct = (current_run["processed_items"] or 0) / max(current_run["total_items"] or 1, 1)
    st.progress(min(pct, 1.0), text=f"{current_run['processed_items']}/{current_run['total_items']} items processed")
    if current_run.get("current_item"):
        st.caption(f"Currently processing: **{current_run['current_item']}** — {current_run.get('current_stage','')}")

    summary = report_generator.summary(db, run_id)

    st.markdown("#### 📊 Numbers — this run")
    cols = st.columns(4)
    with cols[0]: kpi_card("Total Items", summary["total"])
    with cols[1]: kpi_card("🔎 Searching", summary["searching"])
    with cols[2]: kpi_card("✅ Approved (total)", summary["approved_total"])
    with cols[3]: kpi_card("🔍 Human Review", summary["human_review"])
    cols = st.columns(4)
    with cols[0]: kpi_card("↳ Auto Approved", summary["auto_approved"])
    with cols[1]: kpi_card("↳ Human Approved", summary["human_approved"])
    with cols[2]: kpi_card("🚫 Rejected", summary["rejected"])
    with cols[3]: kpi_card("⚠️ Errors", summary["errors"])
    if summary.get("not_found"):
        st.caption(f"Also **{summary['not_found']}** item(s) not found by any source.")

    jobs = db.get_jobs(run_id=run_id, limit=100000)
    scores = [j["best_score"] for j in jobs if j.get("best_score") is not None]
    st.markdown("#### Quality & Performance")
    cols = st.columns(4)
    with cols[0]: kpi_card("Avg Best Score", round(sum(scores) / len(scores), 1) if scores else "—")
    with cols[1]: kpi_card("Median Best Score", round(sorted(scores)[len(scores)//2], 1) if scores else "—")
    retries = [j.get("retry_count") or 0 for j in jobs]
    with cols[2]: kpi_card("Avg Retries", round(sum(retries)/len(retries), 2) if retries else "—")
    search_ok = sum(1 for j in jobs if j["status"] not in ("NOT_FOUND", "ERROR"))
    with cols[3]: kpi_card("Search Success Rate", f"{round(100*search_ok/max(len(jobs),1))}%")

    with st.expander("📈 All-time totals (across every run)"):
        all_time = report_generator.summary(db, None)
        cols = st.columns(4)
        with cols[0]: kpi_card("Total Items Ever", all_time["total"])
        with cols[1]: kpi_card("🔎 Currently Searching", all_time["searching"])
        with cols[2]: kpi_card("✅ Approved (total)", all_time["approved_total"])
        with cols[3]: kpi_card("🔍 Human Review Waiting", all_time["human_review"])
        cols = st.columns(4)
        with cols[0]: kpi_card("↳ Auto Approved", all_time["auto_approved"])
        with cols[1]: kpi_card("↳ Human Approved", all_time["human_approved"])
        with cols[2]: kpi_card("🚫 Rejected", all_time["rejected"])
        with cols[3]: kpi_card("⚠️ Errors / Not Found", all_time["errors"] + all_time["not_found"])
        st.caption(
            f"Items already approved and cached in `fetched_items.xlsx` are reused by normalized "
            f"name on future runs instead of re-searching/re-scoring — avoiding wasted API calls "
            f"for the same dish across different menu files."
        )

    st.markdown("#### Source coverage")
    all_candidates = [c for j in jobs for c in db.get_candidates(j["job_id"], attempt=1)]
    from collections import Counter
    coverage = Counter(c["source"] for c in all_candidates if c["availability"] == "EVALUATED" or c["availability"] == "FOUND")
    if coverage:
        st.bar_chart(coverage)
    else:
        st.caption("No candidates evaluated yet.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### Recent failures")
        errors = db.get_jobs(run_id=run_id, status="ERROR", limit=5)
        if errors:
            for j in errors:
                st.markdown(f"- **{j['food_name']}** — {j.get('error_message','')} {status_badge(j['status'])}",
                           unsafe_allow_html=True)
            st.caption("See the Errors page for full detail and retry actions.")
        else:
            st.caption("No errors yet. 🎉")
    with col_b:
        st.markdown("#### Recent items needing review")
        pending = db.get_jobs(run_id=run_id, status="HUMAN_REVIEW", limit=5)
        if pending:
            for j in pending:
                st.markdown(f"- **{j['food_name']}** — score {j.get('best_score')} {status_badge(j['status'])}",
                           unsafe_allow_html=True)
            st.caption("See the Human Review page to approve/reject.")
        else:
            st.caption("Nothing waiting on a human right now.")

    st.divider()
    st.caption(f"Run ID `{run_id}` · started {time.strftime('%Y-%m-%d %H:%M', time.localtime(current_run['started_at']))} "
              f"· status: {current_run['status']}")
