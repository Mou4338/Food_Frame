"""Pixabay -- free, requires an API key from https://pixabay.com/api/docs/"""
import requests
from sources.base import Candidate, SourceResult

SEARCH_URL = "https://pixabay.com/api/"


def fetch_one(query: str, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("SOURCE_ERROR", error="no Pixabay API key configured")
    try:
        resp = requests.get(
            SEARCH_URL,
            params={"key": api_key, "q": query, "image_type": "photo",
                    "orientation": "horizontal", "per_page": 3, "safesearch": "true"},
            timeout=15,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except requests.RequestException as e:
        return SourceResult("SOURCE_ERROR", error=str(e))
    if not hits:
        return SourceResult("SOURCE_NO_RESULT")
    h = hits[0]
    src = h.get("largeImageURL") or h.get("webformatURL")
    if not src:
        return SourceResult("SOURCE_NO_RESULT")
    return SourceResult("FOUND", Candidate(
        source="Pixabay", url=src, width=h.get("imageWidth", 0), height=h.get("imageHeight", 0),
        author=h.get("user", ""), license="Pixabay License (free to use)",
        attribution_url=h.get("pageURL", ""), query=query,
    ))
