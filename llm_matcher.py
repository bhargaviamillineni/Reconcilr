"""
LLM-assisted matcher for ambiguous transactions.

Processes unresolved rows in batches to reduce API costs. All decisions are
logged with full audit trail. Only matching-relevant fields (amount, date,
reference) are sent to the API - no PII. Model responses are validated before
acceptance.
"""

import json
import time
import pandas as pd
import os
import re

from llm_provider import call_llm, PROVIDER
import audit_log
import config

CONFIDENCE_THRESHOLD = config.LLM_CONFIDENCE_THRESHOLD
BATCH_SIZE = config.LLM_BATCH_SIZE
MAX_CANDIDATES_PER_BATCH = config.LLM_MAX_CANDIDATES_PER_BATCH
MAX_LLM_CALLS = config.LLM_MAX_CALLS_PER_RUN


def estimate_llm_cost(num_unresolved_rows: int) -> tuple[int, float]:
    """Estimates number of LLM calls and approximate cost in USD."""
    estimated_calls = min(
        (num_unresolved_rows + BATCH_SIZE - 1) // BATCH_SIZE,  # ceiling division
        MAX_LLM_CALLS
    )
    cost_per_call = config.LLM_COST_PER_CALL.get(PROVIDER, 0.001)
    estimated_cost = estimated_calls * cost_per_call
    return estimated_calls, estimated_cost


def _sanitize_for_prompt(text, max_len=100) -> str:
    """Sanitizes user input to prevent prompt injection attacks."""
    if pd.isna(text):
        return ""
    
    text = str(text)[:max_len]
    
    # Filter common injection patterns
    injection_patterns = [
        (r'(?i)(ignore|disregard|forget).*(previous|above|prior|instruction)', '[FILTERED]'),
        (r'(?i)(system\s*prompt|new\s*instruction)', '[FILTERED]'),
        (r'(?i)you\s*(are|must|should|will)\s*now', '[FILTERED]'),
        (r'(?i)(act|behave|respond)\s*as', '[FILTERED]'),
    ]
    for pattern, replacement in injection_patterns:
        text = re.sub(pattern, replacement, text)
    
    # Escape quotes and control characters
    text = text.replace('"', '\\"').replace("'", "\\'")
    text = text.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    
    # Only ASCII printable
    text = re.sub(r'[^\x20-\x7E]', '', text)
    
    return text


def _extract_json(raw_text: str):
    """Extracts JSON from model response, handling markdown code fences."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _safe_confidence(value) -> float:
    """Coerces confidence value to 0-100 float. Returns 0 on invalid input."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, v))


def _build_batch_prompt(w_batch: list, g_candidates: pd.DataFrame) -> str:
    """Builds batch matching prompt with orders and candidate settlements."""
    orders_text = "\n".join(
        f"- website_id={w.id}, amount={w.amount}, date={w.date}, reference_text='{_sanitize_for_prompt(w.reference_raw)}'"
        for w in w_batch
    )
    candidates_text = "\n".join(
        f"- id={c.id}, amount={c.amount}, date={c.date}, reference_text='{_sanitize_for_prompt(c.reference_raw)}'"
        for c in g_candidates.itertuples()
    )
    return f"""You are reconciling financial transactions. For EACH website
order below, decide which candidate gateway settlement (if any) corresponds
to the same transaction. Two orders should not be matched to the same
settlement -- if two orders seem to fit one settlement, pick the better fit
for it and leave the other as null.

Website orders:
{orders_text}

Candidate gateway settlements (shared pool, date-nearby):
{candidates_text}

Consider that gateway settlements often deduct a small fee (1-3%) from the
order amount, and reference text may be garbled or generic.

Respond with ONLY a valid JSON array, no markdown fences, no other text,
with exactly one object per website order above, in this exact shape:
[{{"website_id": "<id from the list above>", "match_id": "<one of the candidate ids, or null>", "confidence": <0-100 integer>, "reason": "<one short sentence>"}}]
"""


def _call_with_retry(prompt: str, max_attempts: int = 3) -> str:
    """Retries LLM call with exponential backoff on transient failures."""
    last_error = None
    for attempt in range(max_attempts):
        try:
            return call_llm(prompt)
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
    raise last_error


def resolve_unresolved_rows(unresolved_website: pd.DataFrame, unresolved_gateway: pd.DataFrame):
    """Processes unresolved orders via LLM in batches.
    Returns (llm_matches, still_unresolved_website)."""
    llm_matches = []
    resolved_website_ids = set()
    used_gateway_ids = set()
    calls_made = 0

    website_rows = list(unresolved_website.itertuples())

    for batch_start in range(0, len(website_rows), BATCH_SIZE):
        if calls_made >= MAX_LLM_CALLS:
            audit_log.log({"event": "max_llm_calls_reached", "calls_made": calls_made})
            break

        batch = website_rows[batch_start:batch_start + BATCH_SIZE]
        batch_ids = {w.id for w in batch}

        candidates = unresolved_gateway[~unresolved_gateway["id"].isin(used_gateway_ids)]
        if candidates.empty:
            break
        candidates = candidates.head(MAX_CANDIDATES_PER_BATCH)
        candidate_ids = set(candidates["id"])

        prompt = _build_batch_prompt(batch, candidates)
        calls_made += 1

        raw_output = None
        try:
            raw_output = _call_with_retry(prompt)
            parsed = _extract_json(raw_output)
        except json.JSONDecodeError as e:
            audit_log.log({
                "batch_website_ids": list(batch_ids),
                "error": f"malformed JSON from model: {e}",
                "raw_output": raw_output,
            })
            continue
        except Exception as e:
            audit_log.log({
                "batch_website_ids": list(batch_ids),
                "error": f"LLM call failed after retries: {e}",
            })
            continue

        if not isinstance(parsed, list):
            audit_log.log({
                "batch_website_ids": list(batch_ids),
                "anomaly": "expected a JSON array, got something else",
                "raw_output": raw_output,
            })
            continue

        claims = {}
        batch_log = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            website_id = item.get("website_id")
            if website_id not in batch_ids:
                audit_log.log({
                    "anomaly": "model returned website_id not in this batch",
                    "returned_website_id": website_id,
                })
                continue

            match_id = item.get("match_id")
            confidence = _safe_confidence(item.get("confidence"))
            reason = item.get("reason", "")

            if match_id is not None and match_id not in candidate_ids:
                audit_log.log({
                    "website_id": website_id,
                    "anomaly": "model returned match_id not in candidate set",
                    "returned_match_id": match_id,
                })
                match_id = None

            batch_log.append({"website_id": website_id, "match_id": match_id,
                               "confidence": confidence, "reason": reason})

            if match_id and confidence >= CONFIDENCE_THRESHOLD:
                if match_id in claims:
                    prev_website_id, prev_confidence, _ = claims[match_id]
                    if prev_confidence >= confidence:
                        audit_log.log({
                            "anomaly": "conflicting claim on same settlement, lower confidence discarded",
                            "discarded_website_id": website_id,
                            "kept_website_id": prev_website_id,
                            "settlement_id": match_id,
                        })
                        continue
                    else:
                        audit_log.log({
                            "anomaly": "conflicting claim on same settlement, earlier lower-confidence claim replaced",
                            "discarded_website_id": prev_website_id,
                            "kept_website_id": website_id,
                            "settlement_id": match_id,
                        })
                claims[match_id] = (website_id, confidence, reason)

        for match_id, (website_id, confidence, reason) in claims.items():
            llm_matches.append({
                "website_id": website_id,
                "gateway_id": match_id,
                "confidence": confidence,
                "method": "llm-assisted",
                "reason": reason,
            })
            resolved_website_ids.add(website_id)
            used_gateway_ids.add(match_id)

        audit_log.log({
            "batch_website_ids": list(batch_ids),
            "candidate_ids_offered": list(candidate_ids),
            "batch_decisions": batch_log,
            "accepted_count": len(claims),
        })

        time.sleep(0.3)

    still_unresolved_website = unresolved_website[~unresolved_website["id"].isin(resolved_website_ids)]
    return llm_matches, still_unresolved_website
