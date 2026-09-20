"""Thin CLI wrapper kept for compatibility with the original assignment
entrypoint name. Reads all settings from .env (via Secrets) and delegates
to run_batch.run(), which is the real implementation (also used when the
dashboard's "Start Run" button launches a batch as a background process).

Run:  python main.py
"""
from config import Secrets
from run_batch import run

if __name__ == "__main__":
    secrets = Secrets()
    run(secrets.EXCEL_PATH, secrets.SHEET_NAME, secrets.FOOD_NAME_COLUMN)
