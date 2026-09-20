"""Unsplash -- free, requires an Access Key from https://unsplash.com/developers"""
import requests
from sources.base import Candidate, SourceResult

SEARCH_URL = "https://api.unsplash.com/search/photos"


def fetch_one(query: str, access_key: str) -> SourceResult:
    if not access_key:
        return SourceResult("SOURCE_ERROR", error="no Unsplash access key configured")
    try:
        resp = requests.get(
            SEARCH_URL, headers={"Authorization": f"Client-ID {access_key}"},
            params={"query": query, "per_page": 1, "orientation": "landscape"}, timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except requests.RequestException as e:
        return SourceResult("SOURCE_ERROR", error=str(e))
    if not results:
        return SourceResult("SOURCE_NO_RESULT")
    r = results[0]
    src = r["urls"].get("regular") or r["urls"].get("full")
    if not src:
        return SourceResult("SOURCE_NO_RESULT")
    user = r.get("user", {}) or {}
    return SourceResult("FOUND", Candidate(
        source="Unsplash", url=src, width=r.get("width", 0), height=r.get("height", 0),
        author=user.get("name", ""), license="Unsplash License (free to use)",
        attribution_url=r.get("links", {}).get("html", ""), query=query,
    ))
