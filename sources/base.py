"""Shared candidate record + result wrapper used by every source module.

Every source module exposes one function: fetch_one(query, api_key_or_cfg)
-> SourceResult. Each source returns AT MOST one candidate (the "one
candidate per source" rule from the spec) -- picking the best/first result
from its own API rather than pulling a big list, so all five sources compete
on equal footing (one shot each) rather than one source flooding the field.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Candidate:
    source: str
    url: str
    width: int = 0
    height: int = 0
    author: str = ""
    license: str = ""
    attribution_url: str = ""
    query: str = ""


@dataclass
class SourceResult:
    """availability is one of: FOUND / SOURCE_NO_RESULT / SOURCE_ERROR.
    A source that is disabled, missing an API key, or times out reports
    SOURCE_ERROR (or SOURCE_NO_RESULT if it simply found nothing) -- it
    never silently contributes a fake passing score."""
    availability: str
    candidate: Optional[Candidate] = None
    error: str = ""
