"""Batch runner -- reads an Excel menu file and processes every unique dish
through the five-source pipeline, writing everything to the SQLite database
as it goes. Runs as its OWN process (launched by the dashboard, or from the
command line) so the Streamlit UI never blocks: the dashboard just polls
the same database file for live progress.

Usage:
    python run_batch.py path/to/menu.xlsx --sheet Sheet1 --column item_name
"""
import argparse
import os
import re
import sys
import time

import decision_engine
import storage_manager
from config import Secrets, load_config
from db import DB
from drive_uploader import DriveUploader, LocalStorageUploader
from fetched_log import load_fetched, record_fetched
from pipeline import process_food_item
from sheet_reader import SheetManager


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    return name.strip().rstrip(".") or "unnamed_item"


def build_uploader(cfg: dict, secrets: Secrets):
    destination = cfg["storage"]["destination"]
    if destination == "google_drive":
        folder_id = cfg["storage"].get("drive_folder_id")
        if not folder_id:
            raise RuntimeError(
                "storage.destination is 'google_drive' but storage.drive_folder_id is empty in "
                "config.yaml. Set it to the ID of the Drive folder you want images uploaded to "
                "(the long string in the folder's URL), or switch destination to 'local' if you "
                "want images saved under ./approved_images instead."
            )
        # No silent fallback here on purpose: if Drive was explicitly requested,
        # a connection failure should stop the run loudly rather than quietly
        # saving everything into the project folder instead.
        return DriveUploader(secrets.GOOGLE_OAUTH_CLIENT_FILE, folder_id, secrets.GOOGLE_OAUTH_TOKEN_FILE)
    return LocalStorageUploader()


def build_rejected_uploader(cfg: dict, secrets: Secrets):
    """Uploader used purely as an audit trail for rejected items -- a
    separate Drive folder if storage.rejected_drive_folder_id is set,
    otherwise the same approved folder (rejected files get a distinguishing
    filename prefix -- see storage_manager.rejected_filename_prefix)."""
    return storage_manager.get_uploader(cfg, secrets, kind="rejected")


def run(excel_path: str, sheet_name: str, food_column: str, category_column: str | None = None):
    cfg = load_config()
    secrets = Secrets()
    db = DB(secrets.DB_PATH)

    sheet = SheetManager(excel_path, sheet_name, food_column, category_column)
    groups = sheet.group_by_normalized_name()
    total = len(groups)
    print(f"Found {sum(len(g['rows']) for g in groups.values())} row(s), {total} unique dish(es).")

    run_id = db.create_run(os.path.basename(excel_path), total)
    print(f"Run ID: {run_id}")

    try:
        uploader = build_uploader(cfg, secrets)
        rejected_uploader = build_rejected_uploader(cfg, secrets)
    except Exception as e:
        # Record this as a real, visible failed run (status='error') instead
        # of crashing before any database row exists -- otherwise the
        # dashboard just shows "No runs yet" forever with no clue why,
        # while the actual reason sits only in a log file nobody's looking at.
        db.update_run_progress(run_id, current_stage=f"FATAL (setup): {e}")
        db.finish_run(run_id, status="error")
        print(f"FATAL: {e}", file=sys.stderr)
        raise

    fetched = load_fetched(secrets.FETCHED_LOG_PATH)

    try:
        for i, (normalized, g) in enumerate(groups.items(), start=1):
            db.update_run_progress(run_id, processed_items=i - 1, current_item=g["display_name"],
                                   current_stage="searching five sources")

            cached = fetched.get(normalized)
            if cached and cached.get("drive_link"):
                # Already fetched + approved in a previous run (any input file) --
                # reuse that Drive link instead of re-searching/re-scoring/re-AI-checking.
                job_id = db.create_job(run_id, g["display_name"], normalized, g["category"], g["rows"])
                db.update_job(job_id, status=decision_engine.AUTO_APPROVED, drive_link=cached["drive_link"],
                              selected_source=cached.get("source") or "", best_score=None)
                job = db.get_job(job_id)
                status = job["status"]
                print(f"[{i}/{total}] {g['display_name']} -> reused from fetched_items log ({cached['drive_link']})")
            else:
                job_id = process_food_item(
                    g["display_name"], g["category"], cfg, secrets, db, run_id, g["rows"],
                    uploader=uploader, sanitize_filename=sanitize_filename,
                    rejected_uploader=rejected_uploader,
                )
                job = db.get_job(job_id)
                status = job["status"]
                print(f"[{i}/{total}] {g['display_name']} -> {status} (score={job.get('best_score')})")

                if status == "AUTO_APPROVED" and job.get("drive_link"):
                    record_fetched(secrets.FETCHED_LOG_PATH, g["display_name"], job["drive_link"],
                                   job.get("selected_source") or "")
                    fetched[normalized] = {"food_name": g["display_name"], "drive_link": job["drive_link"]}

            for row_num in g["rows"]:
                if status == "AUTO_APPROVED":
                    sheet.mark_done(row_num, job.get("drive_link") or "", f"auto-approved, score {job.get('best_score')}")
                elif status in ("HUMAN_REVIEW",):
                    sheet.mark_pending_review(row_num, f"needs human review, score {job.get('best_score')}")
                else:
                    sheet.mark_failed(row_num, f"{status}: {job.get('error_message') or job.get('rejection_reason') or ''}")

            if i % 5 == 0 or i == total:
                sheet.save()
            db.update_run_progress(run_id, processed_items=i)
    except Exception as e:
        # A crash here would otherwise leave the run stuck at status='running'
        # forever, with a dead background process -- the dashboard would keep
        # auto-refreshing a run that will never move again, with no visible
        # explanation. Mark it as failed instead so that's obvious.
        sheet.save()
        db.update_run_progress(run_id, current_stage=f"FATAL (crashed): {e}")
        db.finish_run(run_id, status="error")
        print(f"FATAL: {e}", file=sys.stderr)
        raise

    sheet.save()
    db.finish_run(run_id, status="completed")

    from report_generator import save_csv, save_xlsx
    save_xlsx(db, "processing_report.xlsx", run_id)
    save_csv(db, "processing_report.csv", run_id)
    print("\nDone. Report saved to processing_report.xlsx / processing_report.csv")
    print("Open the dashboard (streamlit run app.py) to review Human Review / Rejected / Errors.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the five-source food image pipeline over an Excel menu file.")
    parser.add_argument("excel_path")
    parser.add_argument("--sheet", default=None, help="Sheet/tab name (default: from Secrets/.env or 'Sheet1')")
    parser.add_argument("--column", default=None, help="Food-name column (default: from Secrets/.env or 'item_name')")
    parser.add_argument("--category-column", default=None, help="Optional category column name")
    args = parser.parse_args()

    secrets = Secrets()
    sheet_name = args.sheet or secrets.SHEET_NAME
    food_column = args.column or secrets.FOOD_NAME_COLUMN
    try:
        run(args.excel_path, sheet_name, food_column, args.category_column)
    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
