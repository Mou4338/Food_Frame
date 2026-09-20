"""Central place for two related jobs:

1. Picking which Drive folder an image should land in -- the normal
   "approved" folder (storage.drive_folder_id) or a separate "rejected"
   folder (storage.rejected_drive_folder_id) used purely as an audit trail
   of what was searched and turned down, so nothing meaningful is thrown
   away, but it's also never mixed in with the real menu photos.

2. Deleting local temp copies as soon as they're no longer needed, so the
   project folder never accumulates images that are already safely on
   Drive (or that will never be uploaded because the item was rejected /
   errored out). The ONLY images ever kept on disk beyond the few seconds
   it takes to score them are the best few candidates for an item sitting
   in Human Review -- and even those are deleted the moment a reviewer
   approves or rejects it.

The Kaggle dataset itself is untouched by any of this -- it's the read-only
source folder on disk (or its kagglehub cache), never a "candidate copy"
this module manages, so it's never deleted here.
"""
import os

from drive_uploader import DriveUploader, LocalStorageUploader


def get_uploader(cfg: dict, secrets, kind: str = "approved"):
    """kind: 'approved' or 'rejected'. Returns an uploader pointed at the
    right Drive folder for that kind. Only falls back to local disk if
    Google Drive isn't the configured destination at all -- if
    'google_drive' IS configured but broken (bad folder ID, missing
    client_secret.json, etc), this raises instead of silently saving
    locally, so a broken Drive setup is never masked."""
    storage_cfg = cfg.get("storage", {}) or {}
    destination = storage_cfg.get("destination")

    if destination != "google_drive":
        return LocalStorageUploader(f"./{kind}_images")

    folder_id = storage_cfg.get("drive_folder_id")
    if kind == "rejected":
        folder_id = storage_cfg.get("rejected_drive_folder_id") or folder_id
    if not folder_id:
        raise RuntimeError(
            f"storage.destination is 'google_drive' but no drive_folder_id is set for '{kind}' images. "
            "Set it on the Settings page or in config.yaml."
        )

    # Headless login (Streamlit secrets [drive_token], e.g. on a deployed
    # app with no browser available) takes priority when configured;
    # otherwise fall back to the local client_secret.json + one-time
    # browser login flow.
    if getattr(secrets, "DRIVE_TOKEN_INFO", None):
        return DriveUploader.from_token_info(secrets.DRIVE_TOKEN_INFO, folder_id)
    return DriveUploader(secrets.GOOGLE_OAUTH_CLIENT_FILE, folder_id, secrets.GOOGLE_OAUTH_TOKEN_FILE)


def rejected_uses_same_folder(cfg: dict) -> bool:
    storage_cfg = cfg.get("storage", {}) or {}
    rejected_id = storage_cfg.get("rejected_drive_folder_id")
    return not rejected_id or rejected_id == storage_cfg.get("drive_folder_id")


def rejected_filename_prefix(cfg: dict) -> str:
    """Rejected images get a 'Rejected_' filename prefix whenever they'd
    otherwise land in the very same Drive folder as approved images, so
    the two are never confused just by filename."""
    return "Rejected_" if rejected_uses_same_folder(cfg) else ""


def wrap_sanitize_for_rejected(sanitize_filename, cfg: dict):
    """Returns a sanitize_filename-shaped callable that also applies the
    Rejected_ prefix when appropriate, for reuse with finalize_and_store."""
    prefix = rejected_filename_prefix(cfg)

    def _wrapped(name: str) -> str:
        base = sanitize_filename(name) if sanitize_filename else name
        return f"{prefix}{base}"

    return _wrapped


def candidate_local_paths(evaluations) -> list[str]:
    """Every distinct local_path referenced by a list of candidate/evaluation
    dicts (as produced by pipeline.py / retry_manager.py), in a plain list."""
    paths = []
    for e in evaluations or []:
        p = e.get("local_path") if isinstance(e, dict) else None
        if p and p not in paths:
            paths.append(p)
    return paths


def delete_local_files(paths) -> None:
    for p in paths or []:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except OSError:
            pass  # best-effort cleanup; never let a stray file block the pipeline


def cleanup_job_files(evaluations, keep_paths=None) -> None:
    """Deletes every local temp image belonging to a job's evaluations,
    except any path present in keep_paths (e.g. the top few kept on disk
    while an item waits in Human Review)."""
    keep = set(keep_paths or ())
    to_delete = [p for p in candidate_local_paths(evaluations) if p not in keep]
    delete_local_files(to_delete)


def top_n_local_paths(ranked_evaluations, top_n: int) -> set:
    """The local_path of the best `top_n` *scored* candidates (by rank),
    used to decide what to keep on disk for a Human Review item."""
    return {
        e["local_path"] for e in (ranked_evaluations or [])
        if e.get("rank") and e["rank"] <= top_n and e.get("local_path")
    }
