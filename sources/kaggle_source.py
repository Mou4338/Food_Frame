"""Kaggle source -- local dataset lookup, not a live search API.

Kaggle has no public "search photos by keyword" REST endpoint suitable for
per-item runtime lookups, so this source works differently from the other
four: it needs a folder of food photos on disk to search through.

There are two ways to get that folder:

1. Automatic (recommended): set KAGGLE_DATASET_SLUG in .env (e.g.
   "kmader/food41") plus KAGGLE_USERNAME and KAGGLE_KEY (free, from
   kaggle.com -> your profile -> Account -> "Create New API Token"). The
   first time this source is used it downloads the dataset once via
   `kagglehub` and reuses that local copy for every future run -- no
   further setup needed.
2. Manual: download any food-image dataset yourself and place it under
   KAGGLE_DATASET_DIR (default ./kaggle_dataset), e.g.:
       KAGGLE_DATASET_DIR/chicken_biryani/001.jpg
       KAGGLE_DATASET_DIR/chicken_biryani/002.jpg

Either layout works: per-dish subfolders (searched by folder name) or one
flat folder of images with descriptive filenames (searched by filename).

If no dataset is configured/available, this reports SOURCE_NO_RESULT (not
an error) -- Kaggle simply stays empty and the other four live sources
carry the run. If a dataset slug IS configured but the download itself
fails (bad credentials, no internet), that's reported as SOURCE_ERROR so
it's visible as something worth fixing, rather than silently ignored.
"""
import difflib
import glob
import os
import re
from functools import lru_cache

from sources.base import Candidate, SourceResult

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


@lru_cache(maxsize=8)
def _ensure_dataset(dataset_dir: str, dataset_slug: str):
    """Returns (resolved_root_dir, error). Downloads the configured Kaggle
    dataset via kagglehub the first time it's needed and caches the result
    (both via lru_cache for this process, and via kagglehub's own on-disk
    cache for every future run) so it is never re-downloaded needlessly."""
    if dataset_dir and os.path.isdir(dataset_dir) and os.listdir(dataset_dir):
        return dataset_dir, ""
    if not dataset_slug:
        return "", "no local Kaggle dataset folder configured (set KAGGLE_DATASET_DIR or KAGGLE_DATASET_SLUG)"
    try:
        import kagglehub
    except ImportError:
        return "", "kagglehub is not installed (pip install kagglehub) -- needed to auto-download KAGGLE_DATASET_SLUG"
    try:
        path = kagglehub.dataset_download(dataset_slug)
    except Exception as e:
        return "", f"could not download Kaggle dataset '{dataset_slug}': {e}"
    return path, ""


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")


def _find_matching_folder(root: str, query: str) -> str | None:
    """Finds the Kaggle dataset folder whose name contains the FULL item
    name being searched for -- e.g. item "chicken tandoori" matches a
    dataset folder/image named "chicken_tandoori_butter" (the whole item
    name is a word-substring of the dataset name), not the other way
    around (a short folder like "chicken" must NOT match just because it
    happens to be a substring of a longer query)."""
    key = _normalize(query)
    if not key:
        return None
    all_dirs, dir_names = [], []
    for dirpath, dirnames, _filenames in os.walk(root):
        for d in dirnames:
            all_dirs.append(os.path.join(dirpath, d))
            dir_names.append(_normalize(d))

    # 1) exact match, or the full item name found as a substring of the
    #    dataset folder name (never the reverse -- a shorter folder name
    #    being a substring of a longer query is not a real match).
    exact_matches = [(d, name) for d, name in zip(all_dirs, dir_names) if name == key]
    if exact_matches:
        return exact_matches[0][0]

    contains_matches = [(d, name) for d, name in zip(all_dirs, dir_names) if name and key in name]
    if contains_matches:
        # Prefer the shortest matching name -- the closest / most specific
        # match to the item name itself (e.g. "chicken_tandoori_masala"
        # over "chicken_tandoori_masala_with_extra_toppings").
        contains_matches.sort(key=lambda pair: len(pair[1]))
        return contains_matches[0][0]

    # 2) fuzzy match as a last-resort fallback, for near-miss spellings
    close = difflib.get_close_matches(key, dir_names, n=1, cutoff=0.6)
    if close:
        idx = dir_names.index(close[0])
        return all_dirs[idx]
    return None


def _images_in(folder: str) -> list[str]:
    files = []
    for ext in IMAGE_EXTS:
        files.extend(glob.glob(os.path.join(folder, f"*{ext}")))
        files.extend(glob.glob(os.path.join(folder, f"*{ext.upper()}")))
    return files


def _image_size(path: str) -> tuple[int, int]:
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return 0, 0


def fetch_one(query: str, key_arg) -> SourceResult:
    """key_arg is a (dataset_dir, dataset_slug) tuple, as passed by
    pipeline.py's _source_key_arg. A bare string is also accepted for
    backward compatibility (treated as dataset_dir with no slug)."""
    if isinstance(key_arg, tuple):
        dataset_dir, dataset_slug = key_arg
    else:
        dataset_dir, dataset_slug = key_arg, ""

    root, err = _ensure_dataset(dataset_dir or "", dataset_slug or "")
    if not root:
        # Only a real download attempt that failed counts as an error --
        # simply having nothing configured is a quiet no-result.
        availability = "SOURCE_ERROR" if dataset_slug else "SOURCE_NO_RESULT"
        return SourceResult(availability, error=err)

    files = []
    folder = _find_matching_folder(root, query)
    if folder:
        files = sorted(_images_in(folder))

    if not files:
        # Flat dataset (no per-dish subfolders) -- match on filename instead.
        # The FULL item name must appear as a substring of the image
        # filename (e.g. item "chicken tandoori" matches the file
        # "chicken_tandoori_butter.jpg"), never the reverse.
        key = _normalize(query)
        for dirpath, _dirnames, filenames in os.walk(root):
            hits = [fn for fn in filenames if fn.lower().endswith(IMAGE_EXTS) and key and key in _normalize(fn)]
            if hits:
                # Prefer the filename closest in length to the item name
                # itself -- the most specific / least "padded" match.
                hits.sort(key=lambda fn: len(_normalize(fn)))
                files = [os.path.join(dirpath, fn) for fn in hits]
                break

    if not files:
        return SourceResult("SOURCE_NO_RESULT")

    path = files[0]
    width, height = _image_size(path)

    return SourceResult("FOUND", Candidate(
        source="Kaggle", url=f"file://{path}", width=width, height=height,
        author="Kaggle dataset", license="Per dataset's Kaggle license -- verify before commercial use",
        attribution_url=f"https://www.kaggle.com/datasets/{dataset_slug}" if dataset_slug else "",
        query=query,
    ))
