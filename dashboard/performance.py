"""Performance page -- throughput, score distribution, retry rate, and
per-source win/failure rates."""
from collections import Counter

import streamlit as st

import report_generator
from dashboard.style import kpi_card


def render(db, cfg):
    st.title("📊 Performance")

    runs = db.get_runs(limit=50)
    run_options = {f"{r['run_id']} ({r['source_file']})": r["run_id"] for r in runs}
    run_options["All runs"] = None
    choice = st.selectbox("Run", list(run_options.keys()))
    run_id = run_options[choice]

    jobs = db.get_jobs(run_id=run_id, limit=100000)
    summary = report_generator.summary(db, run_id)
    total = max(summary["total"], 1)

    cols = st.columns(5)
    with cols[0]: kpi_card("Auto-Approval Rate", f"{round(100*summary['auto_approved']/total)}%")
    with cols[1]: kpi_card("Human-Review Rate", f"{round(100*summary['human_review']/total)}%")
    with cols[2]: kpi_card("Rejection Rate", f"{round(100*summary['rejected']/total)}%")
    with cols[3]: kpi_card("Error Rate", f"{round(100*summary['errors']/total)}%")
    scores = [j["best_score"] for j in jobs if j.get("best_score") is not None]
    with cols[4]: kpi_card("Avg Best Score", round(sum(scores)/len(scores), 1) if scores else "—")

    st.markdown("#### Score distribution")
    if scores:
        buckets = Counter()
        for s in scores:
            buckets[f"{int(s//10)*10}-{int(s//10)*10+9}"] += 1
        st.bar_chart(dict(sorted(buckets.items())))
    else:
        st.caption("No scored items yet.")

    st.markdown("#### Source performance")
    all_candidates = [c for j in jobs for c in db.get_candidates(j["job_id"])]
    sources = sorted({c["source"] for c in all_candidates})
    rows = []
    for s in sources:
        s_candidates = [c for c in all_candidates if c["source"] == s]
        found = [c for c in s_candidates if c["availability"] in ("EVALUATED", "FOUND")]
        scored = [c for c in s_candidates if c.get("final_score") is not None]
        wins = [c for c in s_candidates if c.get("rank") == 1]
        rows.append({
            "Source": s, "Attempts": len(s_candidates), "Availability %": round(100*len(found)/max(len(s_candidates),1)),
            "Avg Score": round(sum(c["final_score"] for c in scored)/len(scored), 1) if scored else None,
            "Win Rate %": round(100*len(wins)/max(len(s_candidates),1)),
        })
    st.dataframe(rows, width='stretch', hide_index=True)
