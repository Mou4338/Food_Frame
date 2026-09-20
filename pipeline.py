"""Six-source orchestration for ONE food item (one processing job).

normalize name -> generate queries -> fetch one candidate per enabled
source -> technical eval -> AI eval (technically-valid candidates only)
-> common final_score -> rank 1-6 -> decision engine -> (if AUTO_APPROVED)
process + upload immediately; otherwise persist everything to the database
so the dashboard's Human Review / Rejected / Errors pages have the full
five-source evidence to show a worker.
"""
import os
import time

from PIL import Image

import decision_engine
import storage_manager
from ai_evaluator import evaluate_with_fallback
from duplicate_detector import average_hash, sha256_of_bytes
from image_processor import compress_to_size, download_image, final_validation, process_image, resize_exact
from image_quality import evaluate_technical
from name_cleaner import normalize_name, query_variants
from scoring import compute_final_score
from sources import foodish_source, kaggle_source, pexels_source, pixabay_source, unsplash_source

SOURCE_FUNCS = {
    "pexels": pexels_source.fetch_one,
    "unsplash": unsplash_source.fetch_one,
    "pixabay": pixabay_source.fetch_one,
    "foodish": foodish_source.fetch_one,
    "kaggle": kaggle_source.fetch_one,
}


def _source_key_arg(source_name: str, secrets, cfg):
    return {
        "pexels": secrets.PEXELS_API_KEY,
        "unsplash": secrets.UNSPLASH_ACCESS_KEY,
        "pixabay": secrets.PIXABAY_API_KEY,
        "foodish": "",
        "kaggle": (secrets.KAGGLE_DATASET_DIR, secrets.KAGGLE_DATASET_SLUG),
    }[source_name]


def fetch_candidates_all_sources(food_name: str, cfg: dict, secrets) -> list[dict]:
    """Returns one dict per enabled source (FOUND / SOURCE_NO_RESULT / SOURCE_ERROR),
    trying successive query variants only for sources that come back empty."""
    enabled_sources = cfg["search"]["sources"]
    variants = query_variants(food_name)
    results = []

    for source_name in enabled_sources:
        fn = SOURCE_FUNCS.get(source_name)
        if fn is None:
            results.append({"source": source_name, "availability": "SOURCE_ERROR", "error": "unknown source"})
            continue
        key_arg = _source_key_arg(source_name, secrets, cfg)
        outcome = None
        for query in variants:
            r = fn(query, key_arg)
            outcome = r
            if r.availability == "FOUND":
                break
            if r.availability == "SOURCE_ERROR":
                break  # a broken/misconfigured source won't fix itself by rephrasing the query
        results.append({
            "source": source_name,
            "availability": outcome.availability,
            "candidate": outcome.candidate,
            "error": outcome.error,
        })
    return results


def evaluate_all_candidates(candidate_results: list[dict], food_name: str, cfg: dict, secrets,
                             temp_dir: str, job_tag: str) -> list[dict]:
    """Downloads + technically evaluates + (optionally) AI-evaluates every
    FOUND candidate. Returns a list of evaluation dicts (unsorted)."""
    ai_enabled = cfg["ai"]["enabled"] and bool(secrets.GEMINI_API_KEY or secrets.GROQ_API_KEY)
    quality_cfg = cfg["quality"]
    weights = cfg["scoring"]
    os.makedirs(temp_dir, exist_ok=True)

    evaluations = []
    for entry in candidate_results:
        source = entry["source"]
        if entry["availability"] != "FOUND":
            evaluations.append({**entry, "status": entry["availability"]})
            continue

        cand = entry["candidate"]
        try:
            img: Image.Image = download_image(cand.url)
            raw_bytes = compress_to_size(img, max_size_kb=999999, min_quality=95)  # near-lossless, just to hash/size
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

        local_path = os.path.join(temp_dir, f"{job_tag}_{source}.jpg")
        img.save(local_path, format="JPEG", quality=90)

        if not tech.passed:
            evaluations.append({
                **entry, "status": "TECH_FAIL", "technical_score": tech.score, "reason": tech.reason,
                "composition_score": tech.composition_score, "color_quality_score": tech.color_quality_score,
                "coverage_ratio": tech.coverage_ratio,
                "local_path": local_path, "width": img.size[0], "height": img.size[1],
                "file_size_kb": len(raw_bytes) / 1024, "sha256": sha256_of_bytes(raw_bytes),
                "phash": average_hash(img),
            })
            continue

        ai_score = ai_composition = ai_confidence = None
        ai_json = None
        ai_failed = False
        ai_error_detail = None
        if ai_enabled:
            ai_result = evaluate_with_fallback(img, food_name, secrets, cfg)
            if ai_result.ok:
                ai_score, ai_composition, ai_confidence = ai_result.score, ai_result.composition_score, ai_result.confidence
                ai_json = dict(ai_result.raw or {})
                ai_json["_ai_provider"] = ai_result.provider  # which provider actually answered (gemini or groq fallback)
            else:
                ai_failed = True  # AI failure -> flagged, never silently treated as a pass
                ai_error_detail = ai_result.error

        # Composition score fed into the final blend: if AI vision ran, average
        # its semantic judgement with the measured (GrabCut-based) technical
        # composition score; otherwise the technical measurement stands alone.
        composition_for_scoring = (
            round((ai_composition + tech.composition_score) / 2, 1)
            if ai_composition is not None else tech.composition_score
        )

        resolution_score = min(100.0, 40 + (img.size[0] * img.size[1]) / 1_000_000 * 15)
        breakdown = compute_final_score(tech.score, resolution_score, ai_score, composition_for_scoring, weights)

        evaluations.append({
            **entry,
            "status": "AI_ERROR" if ai_failed else "EVALUATED",
            "technical_score": tech.score,
            "ai_score": ai_score,
            "composition_score": composition_for_scoring,
            "color_quality_score": tech.color_quality_score,
            "coverage_ratio": tech.coverage_ratio,
            "resolution_score": resolution_score,
            "final_score": breakdown.final_score if not ai_failed else None,
            "reason": ai_error_detail if ai_failed else (tech.reason if not ai_json else ai_json.get("reason", tech.reason)),
            "warnings": tech.warnings,
            "ai_json": ai_json,
            "local_path": local_path,
            "width": img.size[0], "height": img.size[1],
            "file_size_kb": len(raw_bytes) / 1024,
            "sha256": sha256_of_bytes(raw_bytes),
            "phash": average_hash(img),
        })
    return evaluations


def rank_candidates(evaluations: list[dict]) -> list[dict]:
    scored = [e for e in evaluations if e.get("final_score") is not None]
    scored.sort(key=lambda e: e["final_score"], reverse=True)
    for i, e in enumerate(scored, start=1):
        e["rank"] = i
    unscored = [e for e in evaluations if e.get("final_score") is None]
    for e in unscored:
        e["rank"] = None
    return scored + unscored


def finalize_and_store(food_name: str, best: dict, cfg: dict, uploader, sanitize_filename) -> tuple[str, str, str]:
    """Runs final resize/compress/validate/upload for the SELECTED candidate.
    Returns (drive_link, filename, error_message)."""
    img_cfg = cfg["image"]
    try:
        img = Image.open(best["local_path"]).convert("RGB")
        image_bytes = process_image(img, img_cfg["width"], img_cfg["height"], img_cfg["max_size_mb"] * 1024)
        ok, msg = final_validation(image_bytes, img_cfg["width"], img_cfg["height"], img_cfg["max_size_mb"] * 1024)
        if not ok:
            return "", "", f"final validation failed: {msg}"
    except Exception as e:
        return "", "", f"processing error: {e}"

    safe_name = sanitize_filename(food_name) if sanitize_filename else food_name
    filename = f"{safe_name}.jpg"
    try:
        drive_link = uploader.upload_image(filename, image_bytes)
    except Exception as e:
        return "", filename, f"upload error: {e}"
    return drive_link, filename, ""


def process_food_item(food_name: str, category: str, cfg: dict, secrets, db, run_id: str,
                                  excel_rows: list, uploader=None, sanitize_filename=None,
                                  rejected_uploader=None) -> int:
    """Full pipeline for one (deduplicated) food item. Writes the job +
    every candidate to the database and returns the job_id.

    Local temp copies of every candidate image are deleted as soon as
    they're no longer needed:
      - AUTO_APPROVED: the winner is uploaded straight to Drive, then every
        local copy for this job is deleted immediately -- nothing about an
        auto-approved item is ever left sitting on disk.
      - HUMAN_REVIEW: only the top `review.top_n` (default 3) scoring
        candidates are kept on disk (for the reviewer to look at); every
        other candidate's file is deleted right away.
      - REJECTED: the best candidate is still uploaded to Drive (the
        rejected-items folder, if configured, else the same approved
        folder with a "Rejected_" filename prefix) as an audit record,
        then every local copy is deleted.
      - NOT_FOUND / ERROR: nothing usable was produced, so any local files
        (e.g. a technically-failed download) are deleted right away too.
    """
    normalized = normalize_name(food_name)
    job_id = db.create_job(run_id, food_name, normalized, category, excel_rows)
    job_tag = f"job{job_id}"
    ranked = []

    try:
        raw_results = fetch_candidates_all_sources(food_name, cfg, secrets)
        evaluations = evaluate_all_candidates(raw_results, food_name, cfg, secrets, secrets.TEMP_IMAGE_DIR, job_tag)
        ranked = rank_candidates(evaluations)

        for e in ranked:
            db.add_candidate(
                job_id,
                attempt=1, source=e["source"], availability=e.get("status", e["availability"]),
                url=(e.get("candidate").url if e.get("candidate") else None),
                local_path=e.get("local_path"), query=(e.get("candidate").query if e.get("candidate") else None),
                author=(e.get("candidate").author if e.get("candidate") else None),
                license=(e.get("candidate").license if e.get("candidate") else None),
                attribution_url=(e.get("candidate").attribution_url if e.get("candidate") else None),
                width=e.get("width"), height=e.get("height"), file_size_kb=e.get("file_size_kb"),
                technical_score=e.get("technical_score"), ai_score=e.get("ai_score"),
                composition_score=e.get("composition_score"), color_quality_score=e.get("color_quality_score"),
                resolution_score=e.get("resolution_score"),
                final_score=e.get("final_score"), rank=e.get("rank"),
                ai_json=str(e.get("ai_json")) if e.get("ai_json") else None,
                reason=e.get("reason") or e.get("error"),
                warnings=str(e.get("warnings")) if e.get("warnings") else None,
            )

        scored = [e for e in ranked if e.get("final_score") is not None]
        any_ai_error = any(e.get("status") == "AI_ERROR" for e in ranked)

        if not scored:
            if any_ai_error:
                db.update_job(job_id, status=decision_engine.ERROR, error_type="AI_EVALUATION_FAILURE",
                              error_message="AI vision evaluation failed for all technically-valid candidates")
            else:
                db.update_job(job_id, status=decision_engine.NOT_FOUND,
                              error_message="No usable candidate from any enabled source")
            storage_manager.cleanup_job_files(ranked)
            return job_id

        best = scored[0]
        best_score = best["final_score"]
        decision_cfg = cfg["decision"]
        status = decision_engine.decide(best_score, decision_cfg["auto_approve"], decision_cfg["human_review_min"])

        db.update_job(job_id, best_score=best_score, selected_source=best["source"])

        if status == decision_engine.AUTO_APPROVED and uploader is not None:
            drive_link, filename, err = finalize_and_store(food_name, best, cfg, uploader, sanitize_filename)
            if err:
                db.update_job(job_id, status=decision_engine.ERROR, error_type="PROCESSING_OR_UPLOAD",
                              error_message=err)
            else:
                db.update_job(job_id, status=decision_engine.AUTO_APPROVED, drive_link=drive_link)
            storage_manager.cleanup_job_files(ranked)  # uploaded (or unrecoverable) -> nothing to keep locally

        elif status == decision_engine.HUMAN_REVIEW:
            top_n = (cfg.get("review", {}) or {}).get("top_n", 3)
            keep = storage_manager.top_n_local_paths(ranked, top_n)
            storage_manager.cleanup_job_files(ranked, keep_paths=keep)
            db.update_job(job_id, status=status)

        elif status == decision_engine.REJECTED:
            if rejected_uploader is not None:
                rej_sanitize = storage_manager.wrap_sanitize_for_rejected(sanitize_filename, cfg)
                r_link, _r_filename, r_err = finalize_and_store(food_name, best, cfg, rejected_uploader, rej_sanitize)
                db.update_job(job_id, status=status, drive_link=(r_link if not r_err else None))
            else:
                db.update_job(job_id, status=status)
            storage_manager.cleanup_job_files(ranked)  # recorded on Drive (or unrecoverable) -> delete locally

        else:
            db.update_job(job_id, status=status)
            storage_manager.cleanup_job_files(ranked)

    except Exception as e:
        db.update_job(job_id, status=decision_engine.ERROR, error_type="PIPELINE_EXCEPTION", error_message=str(e))
        storage_manager.cleanup_job_files(ranked)

    return job_id
