"""Shared CSS for the dashboard -- two selectable themes:

  Light  -- white background, blue accent
  Dark   -- black background, gold accent

Status colors (green/amber/red/gray) stay consistent in meaning across
both themes, just tuned for contrast on each background.
"""
import streamlit as st

THEMES = {
    "light": {
        "BG": "#FFFFFF",
        "CARD_BG": "#F4F8FF",
        "SIDEBAR_BG": "#EAF1FC",
        "TEXT": "#0B1B33",
        "MUTED": "#4A5A72",
        "ACCENT": "#1B5FBF",       # blue
        "GREEN": "#1E7A46",
        "AMBER": "#B8791A",
        "RED": "#C4433B",
        "GRAY": "#5B6472",
        "BORDER": "#DCE6F5",
    },
    "dark": {
        "BG": "#0B0B0C",
        "CARD_BG": "#1A1710",
        "SIDEBAR_BG": "#141210",
        "TEXT": "#F3E7C9",
        "MUTED": "#C9B98D",
        "ACCENT": "#D4AF37",       # gold
        "GREEN": "#3FA96B",
        "AMBER": "#E0A83E",
        "RED": "#E0645A",
        "GRAY": "#9C9484",
        "BORDER": "#33301F",
    },
}


def _css(t: dict) -> str:
    return f"""
<style>
.stApp {{ background-color: {t['BG']}; color: {t['TEXT']}; }}
.block-container {{ padding-top: 2.5rem; padding-bottom: 3rem; max-width: 1200px; }}
h1, h2, h3 {{ color: {t['TEXT']}; font-family: 'Georgia', 'Times New Roman', serif; margin-top: 0.6em; margin-bottom: 0.6em; }}
p, span, label, .stMarkdown, .stCaption {{ color: {t['TEXT']}; }}
[data-testid="stSidebar"] {{ background-color: {t['SIDEBAR_BG']}; }}
[data-testid="stSidebar"] * {{ color: {t['TEXT']}; }}
[data-testid="stMetricValue"] {{ color: {t['TEXT']}; }}
[data-testid="stVerticalBlock"] {{ gap: 0.9rem; }}
[data-testid="column"] {{ padding: 0 8px; }}
div[data-testid="stHorizontalBlock"] {{ margin-bottom: 0.5rem; }}

.kpi-card {{
    background: {t['CARD_BG']}; border-radius: 12px; padding: 20px 22px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.15); border-left: 5px solid {t['ACCENT']};
    margin-bottom: 6px;
}}
.kpi-value {{ font-size: 30px; font-weight: 700; color: {t['TEXT']}; }}
.kpi-label {{ font-size: 13px; color: {t['MUTED']}; text-transform: uppercase; letter-spacing: .04em; }}

.review-card {{
    background: {t['CARD_BG']}; border-radius: 14px; padding: 20px;
    box-shadow: 0 1px 6px rgba(0,0,0,0.18); margin-bottom: 18px;
}}
.candidate-card {{
    background: {t['CARD_BG']}; border: 1px solid {t['BORDER']}; border-radius: 10px;
    padding: 10px; text-align: center;
}}
.candidate-card.winner {{ border: 2px solid {t['GREEN']}; box-shadow: 0 0 0 3px rgba(30,122,70,0.18); }}
.candidate-card.missing {{ opacity: 0.55; }}

.badge {{ display:inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight:600; }}
.badge-green {{ background: rgba(30,122,70,0.16); color: {t['GREEN']}; }}
.badge-amber {{ background: rgba(184,121,26,0.18); color: {t['AMBER']}; }}
.badge-red {{ background: rgba(178,59,59,0.16); color: {t['RED']}; }}
.badge-gray {{ background: rgba(107,98,89,0.16); color: {t['GRAY']}; }}

.stButton>button {{ border-radius: 8px; font-weight: 600; }}
.stButton>button[kind="primary"] {{ background-color: {t['ACCENT']}; border-color: {t['ACCENT']}; color: {'#0B0B0C' if t['ACCENT'] == '#D4AF37' else '#FFFFFF'}; }}

[data-testid="stExpander"] {{ background-color: {t['CARD_BG']}; border-radius: 10px; border: 1px solid {t['BORDER']}; }}
hr {{ border-color: {t['BORDER']}; }}
</style>
"""


def inject(dark: bool = False):
    theme = THEMES["dark"] if dark else THEMES["light"]
    st.markdown(_css(theme), unsafe_allow_html=True)


def status_badge(status: str) -> str:
    mapping = {
        "AUTO_APPROVED": ("badge-green", "Auto Approved"),
        "HUMAN_APPROVED": ("badge-green", "Approved"),
        "HUMAN_REVIEW": ("badge-amber", "Needs Review"),
        "REJECTED": ("badge-red", "Rejected"),
        "ERROR": ("badge-red", "Error"),
        "NOT_FOUND": ("badge-gray", "Not Found"),
        "PROCESSING": ("badge-gray", "Processing"),
    }
    cls, label = mapping.get(status, ("badge-gray", status or "Unknown"))
    return f'<span class="badge {cls}">{label}</span>'


def kpi_card(label: str, value):
    st.markdown(
        f'<div class="kpi-card"><div class="kpi-value">{value}</div>'
        f'<div class="kpi-label">{label}</div></div>',
        unsafe_allow_html=True,
    )
