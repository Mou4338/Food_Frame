"""Search Again / Repair workflow -- used from the Human Review, Rejected,
and Errors pages. Re-runs candidate retrieval + evaluation for one job
(bumping its retry_count and `attempt` number in the candidates table so
the old five-source evidence is kept for audit) and re-applies the same
80/65 decision rule to the fresh results.
"""
from PIL import Image

import decision_engine
import storage_manager
from fetched_log import record_fetched
from image_processor import compress_to_size, download_image
from image_quality import evaluate_technical
from ai_evaluator import evaluate_with_fallback
from duplicate_detector import average_hash, sha256_of_bytes
from name_cleaner import query_variants
from pipeline import fetch_candidates_all_sources, rank_candidates, finalize_and_store
from scoring import compute_final_score


def search_again(job: dict, cfg: dict, secrets, db, uploader=None, sanitize_filename=None,
                  reviewer: str = "worker", rejected_uploader=None) -> dict:
    """Runs a brand-new five-source retrieval round for this job's food name,
    scores it the same way as the first pass, and updates job status
    according to the 80/65 rule. Returns the updated job dict."""
    job_id = job["job_id"]
    food_name = job["food_name"]
    old_score = job.get("best_score")
    retry_count = (job.get("retry_count") or 0) + 1
    attempt = retry_count + 1
    max_retries = cfg["search"]["max_retries"]

    if retry_count > max_retries:
        db.update_job(job_id, status=decision_engine.REJECTED,
                      rejection_reason=f"exceeded max retries ({max_retries}); needs manual upload")
        db.log_action(job_id, reviewer, "Search Again", reason="max retries exceeded", old_score=old_score)
        return db.get_job(job_id)

    raw_results = fetch_candidates_all_sources(food_name, cfg, secrets)
    job_tag = f"job{job_id}_r{attempt}"
    ai_enabled = cfg["ai"]["enabled"] and bool(secrets.GEMINI_API_KEY or secrets.GROQ_API_KEY)
    quality_cfg = cfg["quality"]
    weights = cfg["scoring"]

    evaluations = []
    for entry in raw_results:
        if entry["availability"] != "FOUND":
            evaluations.append({**entry, "status": entry["availability"]})
            continue
        cand = entry["candidate"]
        try:
            img = download_image(cand.url)
            raw_bytes = compress_to_size(img, max_size_kb=999999, min_quality=95)
        except Exception as e:
            evaluations.append({**entry, "status": "SOURCE_ERROR", "error": f"download failed: {e}"})
            continue

        tech = evaluate_technical(
            img, quality_cfg["min_resolution_width"], quality_cfg["min_resolution_height"],
            quality_cfg["blur_threshold"],
            (quality_cfg["ideal_coverage_min"], quality_cfg["ideal_coverage_max"]),
            quality_cfg["coverage_floor"], quality_cfg["coverage_ceiling"],
            quality_cfg["border_cutoff_fail_ratio"],
        )
        local_path = f"{secrets.TEMP_IMAGE_DIR}/{job_tag}_{entry['source']}.jpg"
        img.save(local_path, format="JPEG", quality=90)

        if not tech.passed:
            evaluations.append({**entry, "status": "TECH_FAIL", "technical_score": tech.score, "reason": tech.reason,
                                "composition_score": tech.composition_score, "color_quality_score": tech.color_quality_score,
                                "local_path": local_path, "width": img.size[0], "height": img.size[1],
                                "file_size_kb": len(raw_bytes) / 1024})
            continue

        ai_score = ai_composition = None
        ai_json, ai_failed, ai_error_detail = None, False, None
        if ai_enabled:
            ai_result = evaluate_with_fallback(img, food_name, secrets, cfg)
            if ai_result.ok:
                ai_score, ai_composition = ai_result.score, ai_result.composition_score
                ai_json = dict(ai_result.raw or {})
                ai_json["_ai_provider"] = ai_result.provider
            else:
                ai_failed = True
                ai_error_detail = ai_result.error

        composition_for_scoring = (
            round((ai_composition + tech.composition_score) / 2, 1)
            if ai_composition is not None else tech.composition_score
        )

        resolution_score = min(100.0, 40 + (img.size[0] * img.size[1]) / 1_000_000 * 15)
        breakdown = compute_final_score(tech.score, resolution_score, ai_score, composition_for_scoring, weights)
        evaluations.append({
            **entry, "status": "AI_ERROR" if ai_failed else "EVALUATED",
            "technical_score": tech.score, "ai_score": ai_score, "composition_score": composition_for_scoring,
            "color_quality_score": tech.color_quality_score,
            "resolution_score": resolution_score, "final_score": breakdown.final_score if not ai_failed else None,
            "reason": ai_error_detail if ai_failed else (tech.reason if not ai_json else ai_json.get("reason", tech.reason)),
            "local_path": local_path, "width": img.size[0], "height": img.size[1],
            "file_size_kb": len(raw_bytes) / 1024,
        })

    ranked = rank_candidates(evaluations)
    for e in ranked:
        db.add_candidate(
            job_id, attempt=attempt, source=e["source"], availability=e.get("status", e["availability"]),
            url=(e.get("candidate").url if e.get("candidate") else None), local_path=e.get("local_path"),
            query=(e.get("candidate").query if e.get("candidate") else None),
            author=(e.get("candidate").author if e.get("candidate") else None),
            license=(e.get("candidate").license if e.get("candidate") else None),
            width=e.get("width"), height=e.get("height"), file_size_kb=e.get("file_size_kb"),
            color_quality_score=e.get("color_quality_score"),
            technical_score=e.get("technical_score"), ai_score=e.get("ai_score"),
            composition_score=e.get("composition_score"), resolution_score=e.get("resolution_score"),
            final_score=e.get("final_score"), rank=e.get("rank"), reason=e.get("reason") or e.get("error"),
        )

    scored = [e for e in ranked if e.get("final_score") is not None]
    new_best_score = scored[0]["final_score"] if scored else None
    decision_cfg = cfg["decision"]
    new_status = decision_engine.decide(new_best_score, decision_cfg["auto_approve"], decision_cfg["human_review_min"]) \
        if scored else decision_engine.NOT_FOUND

    update_fields = {"retry_count": retry_count, "best_score": new_best_score,
                     "selected_source": scored[0]["source"] if scored else None}

    keep_paths = set()
    if new_status == decision_engine.AUTO_APPROVED and uploader is not None and scored:
        drive_link, filename, err = finalize_and_store(food_name, scored[0], cfg, uploader, sanitize_filename)
        if err:
            update_fields.update(status=decision_engine.ERROR, error_type="PROCESSING_OR_UPLOAD", error_message=err)
        else:
            update_fields.update(status=decision_engine.AUTO_APPROVED, drive_link=drive_link)
            record_fetched(secrets.FETCHED_LOG_PATH, food_name, drive_link, scored[0]["source"])
        # Uploaded (or unrecoverable) -> nothing worth keeping locally.

    elif new_status == decision_engine.HUMAN_REVIEW:
        top_n = (cfg.get("review", {}) or {}).get("top_n", 3)
        keep_paths = storage_manager.top_n_local_paths(ranked, top_n)
        update_fields["status"] = new_status

    elif new_status == decision_engine.REJECTED:
        if rejected_uploader is not None and scored:
            rej_sanitize = storage_manager.wrap_sanitize_for_rejected(sanitize_filename, cfg)
            r_link, _r_filename, r_err = finalize_and_store(food_name, scored[0], cfg, rejected_uploader, rej_sanitize)
            update_fields["drive_link"] = r_link if not r_err else None
        update_fields["status"] = new_status

    else:
        update_fields["status"] = new_status

    storage_manager.cleanup_job_files(ranked, keep_paths=keep_paths)

    db.update_job(job_id, **update_fields)
    db.log_action(job_id, reviewer, "Search Again", old_score=old_score, new_score=new_best_score)
    return db.get_job(job_id)
