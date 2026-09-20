"""Foodish -- https://foodish-api.com, free & keyless.

IMPORTANT LIMITATION (read this before relying on Foodish as a main source):
Foodish is NOT a search engine. It only serves random photos from a small,
fixed list of ~11 categories (biryani, burger, butter-chicken, dessert,
dosa, idly, pakode, pasta, pizza, rice, samosa) -- there is no way to ask
it for "Chicken Tandoori Boneless" and get a matching photo back the way
Wikimedia's free-text search could.

This module maps your food name to the closest fixed category by keyword,
and only calls the API when a category actually matches -- otherwise it
reports SOURCE_NO_RESULT rather than returning a random, unrelated dish
photo (which would just get rejected downstream anyway, wasting an AI
evaluation call). In practice this means Foodish will contribute a
candidate for a minority of dish names, not for every dish the way
Wikimedia's freeform search did.

Foodish doesn't publish a machine-readable category list -- add keywords
below if a dish you know should match isn't matching.
"""
import requests

from sources.base import Candidate, SourceResult

API_URL = "https://foodish-api.com/api/images/{category}"

CATEGORY_KEYWORDS = {
    "biryani": ("biryani", "biriyani"),
    "butter-chicken": ("butter chicken",),
    "samosa": ("samosa",),
    "dosa": ("dosa",),
    "idly": ("idly", "idli"),
    "pakode": ("pakora", "pakoda", "pakode"),
    "burger": ("burger",),
    "pizza": ("pizza",),
    "pasta": ("pasta",),
    "rice": ("fried rice", "rice", "pulao", "pilaf"),
    "dessert": ("dessert", "sweet", "gulab jamun", "halwa", "kheer", "ice cream", "cake"),
}


def _match_category(query: str) -> str | None:
    q = (query or "").lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return category
    return None


def fetch_one(query: str, _unused_key: str = "") -> SourceResult:
    category = _match_category(query)
    if not category:
        return SourceResult("SOURCE_NO_RESULT", error="no Foodish category matches this dish name")
    try:
        resp = requests.get(
            API_URL.format(category=category),
            headers={"User-Agent": "FoodImageAgent/1.0 (educational project)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return SourceResult("SOURCE_ERROR", error=str(e))

    image_url = data.get("image")
    if not image_url:
        return SourceResult("SOURCE_NO_RESULT")

    return SourceResult("FOUND", Candidate(
        source="Foodish", url=image_url, width=0, height=0,
        author="Foodish (community-contributed dataset)",
        license="Community-contributed via Foodish; verify before commercial use -- see github.com/surhud004/Foodish#credits",
        attribution_url="https://foodish-api.com/",
        query=query,
    ))
