"""Food-name normalization and search-query generation.

Two separate outputs:
- normalize_name(): a stable "normalized name" used as the de-duplication
  key, so that "Chicken Tandoori", "chicken  tandoori", and
  "Chicken Tandoori [Half]" all map to ONE processing job even though the
  original Excel rows keep their own text for the filename/report.
- query_variants(): a list of source-appropriate search queries, most
  specific first, used to actually query the image sources.
"""
import re
import unicodedata

# Portion / menu-variant qualifiers -- describe how it's sold, not what the
# dish looks like, so they hurt image search / normalization if left in.
NOISE_WORDS = {
    "half", "full", "quarter", "small", "medium", "large", "regular",
    "extra", "special", "combo", "plate", "bowl", "kl", "mini", "jumbo",
    "single", "double", "family", "pack",
}

QUERY_SUFFIXES = [
    "",                                   # exact dish name
    "indian food",
    "restaurant food",
    "plated food",
    "menu photo",
    "professional food photography",
]


def normalize_name(raw_name: str) -> str:
    """Collapses whitespace/punctuation/case/portion-words so duplicate menu
    items (same dish, different category or minor spelling) map to the same
    processing job."""
    name = unicodedata.normalize("NFKC", raw_name or "").strip()
    name = re.sub(r"\[[^\]]*\]", "", name)
    name = re.sub(r"\([^)]*\)", "", name)
    name = re.sub(r"[^\w\s-]", " ", name)          # drop stray punctuation
    name = re.sub(r"\s+", " ", name).strip().lower()
    tokens = [t for t in name.split() if t not in NOISE_WORDS]
    normalized = " ".join(tokens).strip()
    return normalized or name or raw_name.strip().lower()


def clean_for_search(raw_name: str) -> str:
    """Human-readable cleaned dish name (keeps normal casing) for use as the
    base of a search query."""
    name = raw_name.strip()
    name = re.sub(r"\[[^\]]*\]", "", name)
    name = re.sub(r"\([^)]*\)", "", name)
    tokens = name.split()
    kept = [t for t in tokens if t.strip(".,-").lower() not in NOISE_WORDS]
    cleaned = " ".join(kept).strip()
    return cleaned if cleaned else raw_name.strip()


def query_variants(raw_name: str, max_variants: int = 6) -> list[str]:
    """Ordered, increasingly-generic search queries: exact dish, then dish +
    contextual suffixes (indian food / restaurant food / plated food / menu
    photo / professional food photography), used when the exact name alone
    returns nothing usable."""
    base = clean_for_search(raw_name)
    variants = []
    for suffix in QUERY_SUFFIXES:
        q = f"{base} {suffix}".strip()
        if q.lower() not in (v.lower() for v in variants):
            variants.append(q)
        if len(variants) >= max_variants:
            break
    # Last resort: just the last two significant words (core dish),
    # e.g. "KL Special Chicken Biryani" -> "Chicken Biryani"
    tokens = base.split()
    if len(tokens) > 2:
        variants.append(" ".join(tokens[-2:]))
    seen, out = set(), []
    for v in variants:
        key = v.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(v)
    return out
