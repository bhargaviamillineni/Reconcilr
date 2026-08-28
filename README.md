# Reconcilr

**AI-assisted transaction reconciliation that keeps humans in the loop with full audit trails.**

**"Reconcilr — closes the gap between what you sold and what actually landed in your account."**

![Test Coverage](https://img.shields.io/badge/coverage-60%25-yellow) ![Tests](https://img.shields.io/badge/tests-32%20passing-brightgreen) ![Python](https://img.shields.io/badge/python-3.9%2B-blue)

---

## ⚠️ Security Notice

**IMPORTANT**: This project includes sensitive API key management. Before using:

1. **NEVER commit `.env` with real API keys** (it's gitignored by default)
2. Copy `.env.example` to `.env` and add your own API keys
3. If you accidentally expose keys, **revoke them immediately** and generate new ones
4. See [SECURITY.md](SECURITY.md) for full security guidelines

**File Upload Limits**: 10MB max file size, 10,000 max rows (use CLI for larger datasets)

---

## The Problem

E-commerce businesses reconcile thousands of payment gateway settlements against website orders every month. Manual reconciliation is slow, error-prone, and doesn't scale. Pure-AI solutions hallucinate matches, hide their reasoning, and rack up API costs matching rows that simple rules could handle for free.

**Real pain points:**
- Gateway exports use different date formats, deduct fees, mangle reference text
- A single mismatched transaction costs real money (chargebacks, accounting errors)
- Black-box AI gives no explanation when it's wrong
- No one trusts a system that can't explain its decisions

---

## Our Solution

A **two-layer hybrid matcher** that solves 80% of cases with deterministic rules (zero cost, perfect reproducibility), then uses AI only for genuinely ambiguous cases — with full audit trails showing exactly why each decision was made.

### Key Innovation
**Rules-first, AI for edge cases.** Most reconciliation tools are either fully manual or fully AI. We combine both intelligently: cheap deterministic matching eliminates easy cases, expensive LLM calls handle only the hard 20%, with every AI decision logged and explainable.

---

## Key Features

✅ **Hybrid Architecture** – Deterministic matcher handles exact/fuzzy matches; LLM resolves ambiguous cases  
✅ **Cost Transparency** – Shows estimated API cost before making calls  
✅ **Full Audit Trail** – Every AI decision logged with reasoning (confidence scores, match logic)  
✅ **Privacy-First** – Customer names/emails never sent to APIs; phone numbers auto-redacted  
✅ **Order-Independent** – Global assignment algorithm; results never depend on CSV row order  
✅ **Production-Ready** – Retry with backoff, input validation, hallucination detection, **32 automated tests (60% coverage)**  
✅ **Provider-Agnostic** – Swap OpenAI/Gemini with one env var; no vendor lock-in  

---

## How It Works

### Architecture

```
┌─────────────────┐     ┌─────────────────┐
│ Website Orders  │     │ Gateway Settles │
└────────┬────────┘     └────────┬────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │   normalize.py        │  ← Validate, standardize, redact PII
         │   (date/amount/ref)   │
         └───────────┬───────────┘
                     ▼
         ┌───────────────────────┐
         │   matcher.py          │  ← Deterministic: exact match,
         │   (rules-based)       │     fuzzy ref, amount tolerance
         └───────────┬───────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
    ┌─────────┐            ┌──────────┐
    │ Matched │            │Unresolved│
    │  (80%)  │            │  (20%)   │
    └─────────┘            └─────┬────┘
                                 ▼
                    ┌─────────────────────┐
                    │  llm_matcher.py     │  ← Batch API calls,
                    │  (AI-assisted)      │     validate responses
                    └──────────┬──────────┘
                               │
                   ┌───────────┴──────────┐
                   ▼                      ▼
            ┌────────────┐        ┌────────────┐
            │  Resolved  │        │ Exceptions │
            │   (15%)    │        │    (5%)    │
            └────────────┘        └────────────┘
                   │                      │
                   └──────────┬───────────┘
                              ▼
                   ┌─────────────────────┐
                   │  audit_log.jsonl    │  ← Every decision
                   │  (full transparency)│     traceable
                   └─────────────────────┘
```

### Core Algorithm

**Phase 1: Deterministic Matching**
1. Score every plausible order-settlement pair (reference match, amount within tolerance, date proximity)
2. Assign matches **globally** by descending confidence (prevents order-dependent bugs)
3. Auto-match rows above 80% confidence threshold
4. Pass unresolved rows to Phase 2

**Phase 2: LLM-Assisted Matching**
1. Batch unresolved orders (8 per API call) to reduce cost
2. Send only: transaction ID, amount, date, sanitized reference (no customer PII)
3. LLM reasons about fee deductions, garbled text, date lags
4. Validate every response (hallucinated IDs rejected)
5. Resolve within-batch conflicts by confidence
6. Log every decision with reasoning

**Phase 3: Human Review**
- Exceptions exported to CSV with LLM explanations
- Accountants review, then re-run with adjusted thresholds or manual matches

---

## Tech Stack

- **Language:** Python 3.11+
- **Data Processing:** pandas, rapidfuzz (fuzzy matching)
- **AI:** OpenAI (gpt-4o-mini) / Google Gemini (2.0-flash) – switchable via env var
- **UI:** Streamlit (demo), CLI (production)
- **Testing:** pytest (26 test cases)
- **Deployment:** Runs locally (no cloud dependencies)

---

## Demo

### CLI Output
```bash
$ python main.py

Loading and normalizing sources...
Running deterministic matcher...
  Auto-matched: 45  |  Unresolved: 13 website rows

💰 Cost estimate: ~2 LLM calls (approx. $0.0002)
   Provider: gemini, Max calls cap: 50

Running LLM-assisted matcher on unresolved rows...
  LLM resolved: 8  |  Still unresolved: 5

Wrote output/matched_transactions.csv (53 rows)
Wrote output/exceptions.csv (5 rows)
Wrote output/audit_log.jsonl (every LLM decision, with reasoning)

--- Accuracy against ground truth ---
Precision: 100.0%  |  Recall: 91.4%  |  False positives: 0
```

### Streamlit UI
Run with `streamlit run app.py`:
- Upload custom CSVs or use bundled samples
- See real-time matching progress
- View matched transactions, exceptions, audit log in tabs
- Cost estimate shown before API calls

---

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API key
cp .env.example .env
# Edit .env: add your OPENAI_API_KEY or GEMINI_API_KEY

# 3. Generate test data
python generate_data.py

# 4. Run reconciliation
python main.py                      # Full pipeline
python main.py --skip-llm           # Deterministic only (free)
streamlit run app.py                # Interactive UI

# 5. Run tests
pytest -v                           # 26 tests
```

**⚠️ Security:** Never commit `.env` – it's git-ignored by default.

---

## Testing

**26 automated tests** covering:
- ✅ Input validation (missing files, duplicate IDs, unparseable dates)
- ✅ Deterministic matcher correctness (zero false positives on ground truth)
- ✅ Order-independence (same results regardless of CSV row order)
- ✅ LLM hallucination detection (rejects invalid match IDs)
- ✅ Retry logic (succeeds after transient failures)
- ✅ PII redaction (phone numbers masked before LLM transmission)
- ✅ Config mutation bugs (caught before shipping)

Run: `pytest -v`

---

## Security & Privacy

### What Gets Sent to AI APIs
- ✅ Transaction IDs, amounts, dates, sanitized references
- ❌ Customer names, emails, phone numbers, addresses (auto-excluded)

### Protection Layers
1. **Column Filtering:** Only `order_id`, `order_date`, `amount`, `reference` loaded from CSV
2. **PII Redaction:** Phone numbers → `[REDACTED-PHONE]` before LLM/logging
3. **Prompt Sanitization:** Escapes quotes, removes control chars, limits length (prevents injection)
4. **Response Validation:** Hallucinated IDs rejected; only offered candidates accepted
5. **Spend Cap:** `MAX_LLM_CALLS` hard limit prevents runaway costs

### Audit Trail
Every LLM decision logged to `output/audit_log.jsonl`:
```json
{
  "batch_website_ids": ["ORD-1045", "ORD-1046"],
  "batch_decisions": [
    {
      "website_id": "ORD-1045",
      "match_id": "STL-1045",
      "confidence": 85,
      "reason": "amount matches after 2% gateway fee, date lag within window"
    }
  ],
  "timestamp": "2026-08-28T10:30:00Z"
}
```

---

## Performance & Scalability

**Current Performance:**
- 58 transactions processed in ~3 seconds (deterministic + LLM)
- 45 matched deterministically (free, instant)
- 13 sent to LLM (2 API calls at $0.0002 total)

**Scalability:**
- Deterministic layer: O(n²) within date windows, but parallelizable
- LLM layer: Sequential batches (8 rows/call); ~5 min for 1,000 unresolved rows
- **Next step:** Parallel LLM calls with ThreadPoolExecutor (3-5x speedup)

**Cost at Scale:**
- 10,000 transactions → ~$5 for LLM calls (assuming 20% unresolved)
- Deterministic layer free, unlimited usage

---

## Limitations & Future Work

### Current Limitations
- Single-threaded LLM calls (sequential batches)
- No multi-currency support (assumes single currency)
- Phone number redaction only (could expand to emails, credit cards)
- Synthetic test data (no real-world validation yet)

### Planned Improvements
1. **Parallel LLM processing** – ThreadPoolExecutor for 3-5x speedup
2. **LLM response caching** – Avoid duplicate API calls on re-runs
3. **Multi-currency normalization** – Handle USD/EUR/INR in same dataset
4. **Expanded PII detection** – Email, credit card, SSN patterns
5. **Real-world benchmark** – Test on actual e-commerce data
6. **Threshold auto-tuning** – ML-based confidence threshold optimization

---

## Why This Matters

### 1. **Real-World Problem**
Every e-commerce business reconciles payments. Manual = slow. Pure AI = expensive & untrustworthy.

### 2. **Novel Hybrid Approach**
Most tools are 100% rules OR 100% AI. We intelligently combine both: cheap deterministic layer eliminates 80% of work, AI handles only genuinely ambiguous 20%.

### 3. **Explainability**
Every AI decision has a reason. No black boxes. Accountants can audit, adjust thresholds, trust results.

### 4. **Production-Ready Engineering**
- 26 automated tests
- Retry logic with exponential backoff
- Input validation with clear error messages
- Hallucination detection
- PII redaction
- Cost estimation before spending
- Provider-agnostic (no vendor lock-in)

### 5. **Honest Metrics**
Ground truth validation shows real accuracy (100% precision, 91% recall). We report false positives honestly.

---
