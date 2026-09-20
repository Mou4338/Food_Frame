"""Pexels -- free, requires API key from https://www.pexels.com/api/"""
import requests
from sources.base import Candidate, SourceResult

SEARCH_URL = "https://api.pexels.com/v1/search"


def fetch_one(query: str, api_key: str) -> SourceResult:
    if not api_key:
        return SourceResult("SOURCE_ERROR", error="no Pexels API key configured")
    try:
        resp = requests.get(
            SEARCH_URL, headers={"Authorization": api_key},
            params={"query": query, "per_page": 1, "orientation": "landscape"}, timeout=15,
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
    except requests.RequestException as e:
        return SourceResult("SOURCE_ERROR", error=str(e))
    if not photos:
        return SourceResult("SOURCE_NO_RESULT")
    p = photos[0]
    src = p["src"].get("large2x") or p["src"].get("original")
    if not src:
        return SourceResult("SOURCE_NO_RESULT")
    return SourceResult("FOUND", Candidate(
        source="Pexels", url=src, width=p.get("width", 0), height=p.get("height", 0),
        author=p.get("photographer", ""), license="Pexels License (free to use)",
        attribution_url=p.get("url", ""), query=query,
    ))
