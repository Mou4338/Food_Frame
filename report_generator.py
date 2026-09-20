"""Builds the full processing report straight from the database -- every
column the spec asks for (Food Name, Normalized Name, Category, Selected
Source, scores, rank, all-five candidate scores, query, license, resolution,
file size, Drive URL, status, retries, error, timestamp).
"""
import datetime
import json

import openpyxl

REPORT_COLUMNS = [
    "Food Name", "Normalized Name", "Category", "Status", "Best/Final Score",
    "Selected Source", "AI Score", "Technical Score", "Composition Score",
    "All Six Candidate Scores", "Search Query", "License", "Resolution",
    "File Size (KB)", "Drive Link", "Description", "Retry Count",
    "Rejection Reason", "Error", "Reviewer", "Last Updated",
]


def _fmt_ts(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""


def build_report_rows(db, run_id: str | None = None) -> list[list]:
    jobs = db.get_jobs(run_id=run_id, limit=100000)
    rows = []
    for job in jobs:
        candidates = db.get_candidates(job["job_id"], attempt=1)
        best = next((c for c in candidates if c["rank"] == 1), None)
        all_scores = "; ".join(
            f"{c['source']}={c['final_score'] if c['final_score'] is not None else c['availability']}"
            for c in candidates
        )
        rows.append([
            job["food_name"], job["normalized_name"], job.get("category") or "",
            job["status"], job.get("best_score"), job.get("selected_source") or "",
            best.get("ai_score") if best else "", best.get("technical_score") if best else "",
            best.get("composition_score") if best else "", all_scores,
            best.get("query") if best else "", best.get("license") if best else "",
            f"{best.get('width')}x{best.get('height')}" if best and best.get("width") else "",
            round(best.get("file_size_kb"), 1) if best and best.get("file_size_kb") else "",
            job.get("drive_link") or "", job.get("description") or "",
            job.get("retry_count") or 0, job.get("rejection_reason") or "",
            job.get("error_message") or "", job.get("reviewer") or "",
            _fmt_ts(job.get("updated_at")),
        ])
    return rows


def save_xlsx(db, path: str, run_id: str | None = None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Processing Report"
    ws.append(REPORT_COLUMNS)
    for row in build_report_rows(db, run_id):
        ws.append(row)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22
    wb.save(path)


def save_csv(db, path: str, run_id: str | None = None):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REPORT_COLUMNS)
        writer.writerows(build_report_rows(db, run_id))


def summary(db, run_id: str | None = None) -> dict:
    """One-stop set of counters covering every job status, for the
    Overview / Performance pages' numbers sections:
    searching (currently in progress), approved (auto + human, combined
    and split out), human review (waiting), rejected, errors, not found."""
    counts = db.count_jobs_by_status(run_id)
    total = sum(counts.values())
    auto_approved = counts.get("AUTO_APPROVED", 0)
    human_approved = counts.get("HUMAN_APPROVED", 0)
    return {
        "total": total,
        "searching": counts.get("PROCESSING", 0),
        "auto_approved": auto_approved,
        "human_approved": human_approved,
        "approved_total": auto_approved + human_approved,
        "human_review": counts.get("HUMAN_REVIEW", 0),
        "rejected": counts.get("REJECTED", 0),
        "errors": counts.get("ERROR", 0),
        "not_found": counts.get("NOT_FOUND", 0),
    }
