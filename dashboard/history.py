"""Search History page -- every source, query, candidate, score and
decision, across all attempts, for full audit transparency."""
import streamlit as st


def render(db, cfg):
    st.title("🕘 Search History")
    st.caption("Every candidate ever evaluated, across every attempt and source.")

    candidates = db.all_candidates(limit=5000)
    name_filter = st.text_input("Filter by food name")
    source_filter = st.multiselect("Filter by source", sorted({c["source"] for c in candidates}))

    if name_filter:
        candidates = [c for c in candidates if name_filter.lower() in (c.get("food_name") or "").lower()]
    if source_filter:
        candidates = [c for c in candidates if c["source"] in source_filter]

    rows = [{
        "Food": c.get("food_name"), "Job Status": c.get("job_status"), "Attempt": c["attempt"],
        "Source": c["source"], "Availability": c["availability"], "Query": c.get("query"),
        "Final Score": c.get("final_score"), "AI Score": c.get("ai_score"), "Technical": c.get("technical_score"),
        "Rank": c.get("rank"), "Reason": c.get("reason"),
    } for c in candidates[:1000]]
    st.dataframe(rows, width='stretch', hide_index=True)
    st.caption(f"Showing {len(rows)} of {len(candidates)} matching records.")
