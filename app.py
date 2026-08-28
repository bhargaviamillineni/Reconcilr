"""
Streamlit UI for the reconciliation pipeline.
Uses the same matching functions as the CLI for consistency.

Run with: streamlit run app.py
"""

import os
import tempfile
import atexit

import pandas as pd
import streamlit as st

import config
import audit_log
import llm_provider
from normalize import load_website_orders, load_gateway_settlement
from matcher import run_deterministic_matching
from llm_matcher import resolve_unresolved_rows, estimate_llm_cost

st.set_page_config(page_title="AI Transaction Reconciler", layout="wide")
st.title("AI-Assisted Transaction Reconciler")
st.caption("Rules-first matching, LLM only for ambiguous cases, full audit trail.")

# Track temp files for cleanup
_temp_files = []

def _cleanup_temp_files():
    """Clean up all temporary files on app exit."""
    for path in _temp_files:
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

atexit.register(_cleanup_temp_files)


def _save_upload(uploaded_file):
    """Saves uploaded file to temp location for processing with size validation."""
    if uploaded_file is None:
        return None
    
    # Validate file size (max 10MB)
    MAX_FILE_SIZE_MB = 10
    file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large ({file_size_mb:.1f}MB). Maximum allowed: {MAX_FILE_SIZE_MB}MB. "
            f"For larger files, use the CLI version: python main.py"
        )
    
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    tmp.write(uploaded_file.getvalue())
    tmp.close()
    
    # Track for cleanup
    _temp_files.append(tmp.name)
    
    return tmp.name


def _exception_reasons(website_ids):
    """Extracts LLM decision reasons for unresolved orders."""
    reasons = {}
    for entry in audit_log.read_all():
        for decision in entry.get("batch_decisions", []):
            website_id = decision.get("website_id")
            if website_id in website_ids:
                match_id = decision.get("match_id")
                confidence = decision.get("confidence", 0)
                reason = decision.get("reason") or "the model did not provide a reason"
                if match_id is None:
                    reasons[website_id] = f"LLM: no confident candidate ({confidence:.0f}/100) - {reason}"
                else:
                    reasons[website_id] = f"LLM confidence below threshold ({confidence:.0f}/100) - {reason}"
    return reasons


with st.sidebar:
    st.header("Settings")

    use_llm = st.checkbox("Use LLM-assisted matching", value=True)
    if use_llm:
        ready, msg = llm_provider.check_provider_ready()
        if ready:
            st.success(f"{msg}")
        else:
            st.warning(f"{msg}")
            st.caption("Will fall back to deterministic-only matching for this run.")

    st.divider()
    st.subheader("Data source")
    data_source = st.radio(
        "Choose data", ["Use bundled sample data", "Upload my own CSVs"],
        label_visibility="collapsed",
    )

    website_file = gateway_file = ground_truth_file = None
    if data_source == "Upload my own CSVs":
        st.info("🔒 **Privacy:** Only order ID, amount, date, and reference fields are used. Customer names, emails, and other columns are automatically excluded and never sent to any API.")
        website_file = st.file_uploader("Website orders CSV", type="csv")
        gateway_file = st.file_uploader("Gateway settlement CSV", type="csv")
        ground_truth_file = st.file_uploader(
            "Ground truth CSV (optional -- enables accuracy scoring)", type="csv"
        )
    else:
        st.caption(f"Using `{config.WEBSITE_ORDERS_PATH}` and `{config.GATEWAY_SETTLEMENT_PATH}`")

    run_clicked = st.button("Run Reconciliation", type="primary", width='stretch')


if not run_clicked:
    st.info("Configure your data source in the sidebar, then click **Run Reconciliation**.")
    st.stop()

if data_source == "Upload my own CSVs":
    if not website_file or not gateway_file:
        st.error("Please upload both a website orders CSV and a gateway settlement CSV.")
        st.stop()
    
    try:
        website_path = _save_upload(website_file)
        gateway_path = _save_upload(gateway_file)
        ground_truth_path = _save_upload(ground_truth_file)
    except ValueError as e:
        st.error(f"File upload error: {e}")
        st.stop()
else:
    website_path = config.WEBSITE_ORDERS_PATH
    gateway_path = config.GATEWAY_SETTLEMENT_PATH
    ground_truth_path = config.GROUND_TRUTH_PATH if os.path.exists(config.GROUND_TRUTH_PATH) else None

try:
    with st.spinner("Loading and normalizing sources..."):
        website_df = load_website_orders(website_path)
        gateway_df = load_gateway_settlement(gateway_path)
    
    # Validate row count to prevent memory issues
    MAX_ROWS = 10000
    total_rows = len(website_df) + len(gateway_df)
    if total_rows > MAX_ROWS:
        st.error(
            f"Too many rows ({total_rows:,}). Maximum: {MAX_ROWS:,} combined rows. "
            f"For larger datasets, use the CLI version: `python main.py`"
        )
        st.stop()
        
except (FileNotFoundError, ValueError) as e:
    st.error(f"Input error: {e}")
    st.stop()

with st.spinner("Running deterministic matcher..."):
    matched, unresolved_website, unresolved_gateway = run_deterministic_matching(website_df, gateway_df)

llm_matches = []
still_unresolved_website = unresolved_website
llm_ran = False

if use_llm:
    ready, _ = llm_provider.check_provider_ready()
    if ready:
        if len(unresolved_website) > 0:
            estimated_calls, estimated_cost = estimate_llm_cost(len(unresolved_website))
            st.info(f"💰 Estimated cost: ~{estimated_calls} LLM calls (≈${estimated_cost:.4f} using {llm_provider.PROVIDER})")
        
        with st.spinner("Running LLM-assisted matcher on ambiguous rows..."):
            llm_matches, still_unresolved_website = resolve_unresolved_rows(unresolved_website, unresolved_gateway)
        llm_ran = True

all_matches = [
    {"website_id": m.website_id, "gateway_id": m.gateway_id,
     "confidence": m.confidence, "method": m.method, "reason": m.reason}
    for m in matched
] + llm_matches

exception_reasons = _exception_reasons(set(still_unresolved_website["id"])) if llm_ran else {}
exceptions_df = pd.DataFrame({
    "website_id": still_unresolved_website["id"],
    "amount": still_unresolved_website["amount"],
    "date": still_unresolved_website["date"],
    "reason": [
        exception_reasons.get(website_id, "No confident match found by deterministic rules")
        for website_id in still_unresolved_website["id"]
    ],
})

st.subheader("Results")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total orders", len(website_df))
c2.metric("Auto-matched (rules)", len(matched))
c3.metric("LLM-resolved", len(llm_matches))
c4.metric("Exceptions", len(exceptions_df))

if ground_truth_path and os.path.exists(ground_truth_path):
    truth = pd.read_csv(ground_truth_path)
    true_matches = set((r.order_id, r.settlement_id) for r in truth.itertuples() if r.is_match)
    predicted = set((m["website_id"], m["gateway_id"]) for m in all_matches)
    tp = predicted & true_matches
    fp = predicted - true_matches
    precision = len(tp) / len(predicted) if predicted else 0
    recall = len(tp) / len(true_matches) if true_matches else 0

    st.subheader("Accuracy against ground truth")
    a1, a2, a3 = st.columns(3)
    a1.metric("Precision", f"{precision:.1%}")
    a2.metric("Recall", f"{recall:.1%}")
    a3.metric("False positives", len(fp))
    if fp:
        st.caption(f"⚠ {len(fp)} incorrect match(es) - review recommended.")

tab1, tab2, tab3 = st.tabs(["Matched transactions", "Exceptions", "Audit log"])

with tab1:
    st.dataframe(pd.DataFrame(all_matches), width='stretch', hide_index=True)

with tab2:
    st.dataframe(exceptions_df, width='stretch', hide_index=True)
    if exceptions_df.empty:
        st.caption("No exceptions -- everything was resolved.")

with tab3:
    if llm_ran:
        entries = audit_log.read_all()
        st.caption(f"{len(entries)} audit entries logged - full decision trace.")
        st.json(entries[-20:] if len(entries) > 20 else entries)
    else:
        st.info("No LLM calls made this run.")
