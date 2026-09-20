"""Food Image Automation Agent -- Dashboard entrypoint.

Run with:   streamlit run app.py

A worker-facing, multipage Streamlit dashboard for monitoring the
five-source image-selection pipeline, reviewing only uncertain (65-79.99)
results, recovering failures, and tracking quality/performance -- built as
an exception-management system, not a gallery of every image.
"""
import streamlit as st

from config import Secrets, load_config
from dashboard import approved, errors, history, human_review, overview, performance, rejected, settings
from dashboard.style import inject
from db import DB

st.set_page_config(page_title="Food Image Agent", page_icon="🍽️", layout="wide")

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False

secrets = Secrets()
cfg = load_config()
db = DB(secrets.DB_PATH)

PAGES = {
    "Overview": overview,
    "Human Review": human_review,
    "Rejected": rejected,
    "Errors / Failed Jobs": errors,
    "Auto Approved": approved,
    "Performance": performance,
    "Search History": history,
    "Settings": settings,
}

# Badge counts next to the pages that need attention, so a worker can see
# at a glance where the backlog is without opening each page.
counts = db.count_jobs_by_status()
labels = {
    "Overview": "Overview",
    "Human Review": f"Human Review ({counts.get('HUMAN_REVIEW', 0)})",
    "Rejected": f"Rejected ({counts.get('REJECTED', 0)})",
    "Errors / Failed Jobs": f"Errors ({counts.get('ERROR', 0) + counts.get('NOT_FOUND', 0)})",
    "Auto Approved": "Auto Approved",
    "Performance": "Performance",
    "Search History": "Search History",
    "Settings": "Settings",
}

st.sidebar.title("🍽️ Food Image Agent")
st.sidebar.caption("Five-source automation with human-in-the-loop review")
st.session_state["dark_mode"] = st.sidebar.toggle("🌙 Dark mode (black + gold)", value=st.session_state["dark_mode"])
inject(dark=st.session_state["dark_mode"])

choice_label = st.sidebar.radio("Navigate", list(labels.values()), label_visibility="collapsed")
selected_page = next(k for k, v in labels.items() if v == choice_label)

st.sidebar.divider()
st.sidebar.caption(f"Database: `{secrets.DB_PATH}`")
st.sidebar.caption(f"Storage: {cfg['storage']['destination']}")

PAGES[selected_page].render(db, cfg)
