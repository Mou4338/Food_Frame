"""The 80 / 65 routing rule -- the one place that decides AUTO_APPROVED vs
HUMAN_REVIEW vs REJECTED. Kept as a single small function so the threshold
logic can never drift between the batch runner and the dashboard.

    score >= 80        -> Auto Approved
    65 <= score < 80    -> Human Review
    score < 65           -> Rejected
"""

AUTO_APPROVED = "AUTO_APPROVED"
HUMAN_REVIEW = "HUMAN_REVIEW"
HUMAN_APPROVED = "HUMAN_APPROVED"
REJECTED = "REJECTED"
SEARCH_AGAIN = "SEARCH_AGAIN"
NOT_FOUND = "NOT_FOUND"
ERROR = "ERROR"


def decide(best_score: float | None, auto_approve_threshold: float = 80,
           human_review_min: float = 65) -> str:
    """best_score is the highest final_score among all technically-valid,
    successfully-evaluated candidates. Pass None if there were zero usable
    candidates (caller should use NOT_FOUND / ERROR instead of calling this)."""
    if best_score is None:
        return NOT_FOUND
    if best_score >= auto_approve_threshold:
        return AUTO_APPROVED
    if best_score >= human_review_min:
        return HUMAN_REVIEW
    return REJECTED
