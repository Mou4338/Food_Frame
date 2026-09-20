"""Combines technical + AI sub-scores into ONE comparable final_score per
candidate, using configurable weights, so all five sources -- whatever
their format or license quirks -- are ranked on equal footing.

If AI vision is disabled (or unavailable) for a run, its weight is
redistributed onto the technical score rather than silently dropping the
candidate's score -- redistribution is an explicit, documented choice, not
a bug: a technical-only score is honestly labelled as such via `ai_used`.
"""
from dataclasses import dataclass


@dataclass
class ScoreBreakdown:
    final_score: float
    technical_score: float
    ai_score: float | None
    composition_score: float | None
    resolution_score: float
    ai_used: bool


def compute_final_score(technical_score: float, resolution_score: float,
                         ai_score: float | None, composition_score: float | None,
                         weights: dict) -> ScoreBreakdown:
    ai_w = weights.get("ai_weight", 0.50)
    tech_w = weights.get("technical_weight", 0.25)
    comp_w = weights.get("composition_weight", 0.15)
    res_w = weights.get("resolution_weight", 0.10)

    if ai_score is None:
        # Redistribute the AI weight onto technical, keep composition/resolution as-is.
        tech_w = tech_w + ai_w
        ai_w = 0.0
        comp_score_for_calc = composition_score if composition_score is not None else technical_score
    else:
        comp_score_for_calc = composition_score if composition_score is not None else ai_score

    final = (
        ai_w * (ai_score or 0)
        + tech_w * technical_score
        + comp_w * comp_score_for_calc
        + res_w * resolution_score
    )
    final = round(max(0.0, min(100.0, final)), 1)
    return ScoreBreakdown(
        final_score=final, technical_score=technical_score, ai_score=ai_score,
        composition_score=composition_score, resolution_score=resolution_score,
        ai_used=ai_score is not None,
    )
