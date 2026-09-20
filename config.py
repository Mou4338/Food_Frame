"""Central configuration for the Six-Source Food Image Automation Agent.

Loads defaults, then overrides from config.yaml (if present), then from
.env / environment variables (highest priority, good for secrets like API
keys). The Settings dashboard page can also write changes back into
config.yaml so they persist across runs without editing files by hand.

Deployed apps (e.g. Streamlit Community Cloud) have no .env file and no
local disk to keep client_secret.json/token.json on. In that case, secrets
are instead entered once in Streamlit's own Secrets manager (Settings ->
Secrets on the app's dashboard), in the same flat KEY = "value" format as
a .env file, plus one nested [drive_token] table for headless Google Drive
login (see generate_drive_token.py for how to produce it). The block below
copies anything found there into the normal environment variables, so
every os.getenv() call below -- and everything the background run_batch.py
subprocess reads via its inherited environment -- picks it up exactly the
same way it would pick up a real .env file. A real .env value already set
always wins, so local development is unaffected.
"""
import json
import os
import yaml
from dotenv import load_dotenv

load_dotenv()

try:
    import streamlit as st
    _st_secrets = st.secrets
except Exception:
    _st_secrets = None

if _st_secrets:
    for _k, _v in _st_secrets.items():
        if _k == "drive_token":
            continue  # nested table, handled separately below
        if isinstance(_v, (str, int, float)) and os.getenv(_k) is None:
            os.environ[_k] = str(_v)
    if "drive_token" in _st_secrets and os.getenv("DRIVE_TOKEN_JSON") is None:
        os.environ["DRIVE_TOKEN_JSON"] = json.dumps(dict(_st_secrets["drive_token"]))

DEFAULT_CONFIG = {
    "image": {"width": 1800, "height": 1200, "max_size_mb": 10},
    "search": {
        "sources": ["pexels", "unsplash", "pixabay", "foodish", "kaggle"],
        "candidates_per_source": 1,
        "max_retries": 3,
    },
    "quality": {
        "min_resolution_width": 900,
        "min_resolution_height": 600,
        "blur_threshold": 80,
        "ideal_coverage_min": 0.80,   # food should fill 80-90% of the frame
        "ideal_coverage_max": 0.90,
        "coverage_floor": 0.15,       # below this: food is barely in the shot -> hard fail
        "coverage_ceiling": 0.97,     # above this: zoomed in / no context left -> hard fail
        "border_cutoff_fail_ratio": 0.55,  # this much of the border is food -> likely cut off
    },
    "scoring": {
        "ai_weight": 0.50,
        "technical_weight": 0.25,
        "composition_weight": 0.15,
        "resolution_weight": 0.10,
    },
    "decision": {"auto_approve": 80, "human_review_min": 65},
    "ai": {"enabled": False, "provider": "gemini", "model": "gemini-flash-latest",
           "groq_model": "openai/gpt-oss-120b"},
    "storage": {
        "destination": "google_drive", "drive_folder_id": "",
        # Optional separate Drive folder for an audit trail of rejected
        # items. Leave blank to store rejected-item photos in the SAME
        # folder as approved ones, distinguished by a "Rejected_" filename
        # prefix (see storage_manager.rejected_filename_prefix).
        "rejected_drive_folder_id": "",
    },
    "review": {
        # How many of the best-scoring candidates a human reviewer sees per
        # item. Every candidate is still scored and recorded in the
        # database for audit purposes; only this many are ever kept as
        # local image files (the rest are deleted immediately to save
        # space) and shown on the Human Review page.
        "top_n": 3,
    },
    "duplicate": {"phash_distance_threshold": 6},
    "logging": {"level": "INFO"},
}

CONFIG_PATH = os.getenv("CONFIG_PATH", "./config.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str = CONFIG_PATH) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)
    return cfg


def save_config(cfg: dict, path: str = CONFIG_PATH):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


class Secrets:
    """API keys & other secrets -- always from environment / .env / Streamlit
    secrets, NEVER written into config.yaml (which may be committed)."""
    PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
    UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
    PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    GOOGLE_OAUTH_CLIENT_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "./client_secret.json")
    GOOGLE_OAUTH_TOKEN_FILE = os.getenv("GOOGLE_OAUTH_TOKEN_FILE", "./token.json")

    # Populated only when a [drive_token] table was supplied via Streamlit
    # secrets (or a DRIVE_TOKEN_JSON env var directly) -- lets Drive log in
    # headlessly using a saved refresh_token, with no client_secret.json
    # file and no browser. None when not configured, in which case the
    # file + one-time-browser flow above is used instead.
    _drive_token_json = os.getenv("DRIVE_TOKEN_JSON", "")
    DRIVE_TOKEN_INFO = json.loads(_drive_token_json) if _drive_token_json else None

    EXCEL_PATH = os.getenv("EXCEL_PATH", "./food_items.xlsx")
    SHEET_NAME = os.getenv("SHEET_NAME", "Sheet1")
    FOOD_NAME_COLUMN = os.getenv("FOOD_NAME_COLUMN", "item_name")

    DB_PATH = os.getenv("DB_PATH", "./agent_data.db")
    TEMP_IMAGE_DIR = os.getenv("TEMP_IMAGE_DIR", "./temp_images")
    FETCHED_LOG_PATH = os.getenv("FETCHED_LOG_PATH", "./fetched_items.xlsx")

    KAGGLE_DATASET_DIR = os.getenv("KAGGLE_DATASET_DIR", "./kaggle_dataset")
    # Slug of a Kaggle dataset (e.g. "kmader/food41") to auto-download the
    # first time it's needed, IF the folder above is empty/missing. Needs
    # KAGGLE_USERNAME + KAGGLE_KEY (from kaggle.com -> Account -> API) set
    # as environment variables, or a ~/.kaggle/kaggle.json file. Leave blank
    # to only use images you've placed in KAGGLE_DATASET_DIR yourself.
    KAGGLE_DATASET_SLUG = os.getenv("KAGGLE_DATASET_SLUG", "")
