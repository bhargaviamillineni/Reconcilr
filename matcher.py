"""
Deterministic matcher.

No AI here on purpose -- this layer should resolve the majority of rows
using plain, explainable, reproducible logic. Only what survives this
layer gets sent to the (paid, non-deterministic) LLM step.

Matching strategy:
  1. Score every website-row / gateway-row pair within a plausible date
     window (exact reference match, amount tolerance, date proximity,
     fuzzy reference similarity).
  2. Assign matches GLOBALLY by descending confidence, not row-by-row in
     whatever order the input happened to arrive in. This matters: a
     naive "first row wins" approach can let a weak fuzzy match claim a
     gateway row before a later, perfect exact match ever gets a chance
     to see it -- an order-dependent bug that produces different (and
     sometimes wrong) results depending on how the CSV rows happen to be
     sorted. Sorting all candidate pairs by score first and assigning
     greedily from the top removes that dependency: the best match in
     the whole dataset always wins its pair first.

Every row gets a confidence score. Rows above CONFIDENCE_THRESHOLD are
auto-matched. Everything else is passed on as "unresolved".
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional
import pandas as pd
from rapidfuzz import fuzz

import config

AMOUNT_TOLERANCE = config.AMOUNT_TOLERANCE
DATE_WINDOW_DAYS = config.DATE_WINDOW_DAYS
CONFIDENCE_THRESHOLD = config.DETERMINISTIC_CONFIDENCE_THRESHOLD


@dataclass
class MatchResult:
    website_id: Optional[str]
    gateway_id: Optional[str]
    confidence: float
    method: str
    reason: str


def score_candidate(w_row, g_row) -> float:
    """Combine exact reference match, amount closeness, date closeness,
    and fuzzy reference similarity into one 0-100 confidence score."""
    score = 0.0

    # Reference signal (0-50 points)
    if w_row.reference and w_row.reference == g_row.reference:
        score += 50
    elif w_row.reference and g_row.reference:
        similarity = fuzz.ratio(w_row.reference, g_row.reference)  # 0-100
        score += 0.35 * similarity  # partial credit, max ~35 points

    # Amount signal (0-30 points) -- linear falloff within tolerance
    amount_diff = abs(w_row.amount - g_row.amount)
    if amount_diff <= AMOUNT_TOLERANCE:
        score += 30 * (1 - amount_diff / max(AMOUNT_TOLERANCE, 0.01))

    # Date signal (0-20 points) -- linear falloff within window
    date_diff = abs((g_row.date - w_row.date).days)
    if date_diff <= DATE_WINDOW_DAYS:
        score += 20 * (1 - date_diff / DATE_WINDOW_DAYS)

    return round(min(score, 100), 1)


def run_deterministic_matching(website_df: pd.DataFrame, gateway_df: pd.DataFrame):
    """
    Returns (matched, unresolved_website, unresolved_gateway)
      matched: list[MatchResult] for rows above CONFIDENCE_THRESHOLD
      unresolved_website / unresolved_gateway: rows with no confident match,
        passed on for LLM-assisted resolution.
    """
    # Step 1: score every plausible pair (bounded by the date window so
    # this stays fast even on larger datasets -- we never compare rows
    # that couldn't possibly be related).
    scored_pairs = []
    for w_row in website_df.itertuples():
        candidates = gateway_df[
            (gateway_df["date"] >= w_row.date - timedelta(days=1)) &
            (gateway_df["date"] <= w_row.date + timedelta(days=DATE_WINDOW_DAYS))
        ]
        for g_row in candidates.itertuples():
            score = score_candidate(w_row, g_row)
            if score >= CONFIDENCE_THRESHOLD:
                scored_pairs.append((score, w_row.id, g_row.id))

    # Step 2: assign globally by descending score. Tie-break on ids so the
    # result is fully reproducible run-to-run given the same input.
    scored_pairs.sort(key=lambda p: (-p[0], str(p[1]), str(p[2])))

    matched = []
    matched_website_ids = set()
    used_gateway_ids = set()

    for score, w_id, g_id in scored_pairs:
        if w_id in matched_website_ids or g_id in used_gateway_ids:
            continue  # one (or both) sides of this pair already claimed by a higher-scoring match
        matched.append(MatchResult(
            website_id=w_id,
            gateway_id=g_id,
            confidence=score,
            method="deterministic",
            reason=f"reference/amount/date score {score}",
        ))
        matched_website_ids.add(w_id)
        used_gateway_ids.add(g_id)

    unresolved_website = website_df[~website_df["id"].isin(matched_website_ids)]
    unresolved_gateway = gateway_df[~gateway_df["id"].isin(used_gateway_ids)]

    return matched, unresolved_website, unresolved_gateway
