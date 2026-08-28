"""
Full reconciliation pipeline: deterministic matching + LLM-assisted resolution.

Usage:
    python main.py
    python main.py --website my_orders.csv --gateway my_settlements.csv
    python main.py --skip-llm
"""

import argparse
import os
import pandas as pd
from normalize import load_website_orders, load_gateway_settlement
from matcher import run_deterministic_matching
from llm_matcher import resolve_unresolved_rows, estimate_llm_cost
import llm_provider
import config


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reconcile website orders against gateway settlements."
    )
    parser.add_argument("--website", default=config.WEBSITE_ORDERS_PATH,
                         help="Path to website orders CSV")
    parser.add_argument("--gateway", default=config.GATEWAY_SETTLEMENT_PATH,
                         help="Path to gateway settlement CSV")
    parser.add_argument("--ground-truth", default=config.GROUND_TRUTH_PATH,
                         help="Path to ground truth CSV (optional)")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR,
                         help="Output directory for results")
    parser.add_argument("--skip-llm", action="store_true",
                         help="Skip LLM-assisted matching")
    return parser.parse_args()


def score_against_ground_truth(all_matches, ground_truth_path: str):
    """Calculates precision, recall, and match rate against ground truth."""
    if not os.path.exists(ground_truth_path):
        print(f"\n(No ground truth file at {ground_truth_path} -- skipping accuracy scoring.)")
        return

    truth = pd.read_csv(ground_truth_path)
    true_matches = set(
        (row.order_id, row.settlement_id)
        for row in truth.itertuples() if row.is_match
    )

    predicted_matches = set((m["website_id"], m["gateway_id"]) for m in all_matches)

    true_positives = predicted_matches & true_matches
    false_positives = predicted_matches - true_matches
    false_negatives = true_matches - predicted_matches

    precision = len(true_positives) / len(predicted_matches) if predicted_matches else 0
    recall = len(true_positives) / len(true_matches) if true_matches else 0
    total_rows = len(truth[truth["order_id"].notna()])
    match_rate = len(predicted_matches) / total_rows if total_rows else 0

    print("\n--- Accuracy against ground truth ---")
    print(f"Total known true matches : {len(true_matches)}")
    print(f"Predicted matches        : {len(predicted_matches)}")
    print(f"True positives           : {len(true_positives)}")
    print(f"False positives          : {len(false_positives)}  <- wrong matches, the costly kind")
    print(f"False negatives          : {len(false_negatives)}  <- missed matches, left as exceptions")
    print(f"Precision                : {precision:.1%}")
    print(f"Recall                   : {recall:.1%}")
    print(f"Auto-match rate          : {match_rate:.1%}")

    if false_positives:
        print("\nFalse positives:")
        for wid, gid in false_positives:
            print(f"  website={wid} <-> gateway={gid}")


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    config.OUTPUT_DIR = args.output_dir

    print("Loading and normalizing sources...")
    website_df = load_website_orders(args.website)
    gateway_df = load_gateway_settlement(args.gateway)

    print("Running deterministic matcher...")
    matched, unresolved_website, unresolved_gateway = run_deterministic_matching(website_df, gateway_df)
    print(f"  Auto-matched: {len(matched)}  |  Unresolved: {len(unresolved_website)} website rows")

    llm_matches = []
    still_unresolved_website = unresolved_website
    llm_actually_ran = False
    if args.skip_llm:
        print("Skipping LLM-assisted matcher (--skip-llm set).")
    else:
        ready, message = llm_provider.check_provider_ready()
        if not ready:
            print(f"\n⚠ LLM unavailable: {message}")
            print("  Fix .env and re-run, or use --skip-llm.\n")
        else:
            if len(unresolved_website) > 0:
                estimated_calls, estimated_cost = estimate_llm_cost(len(unresolved_website))
                print(f"\n💰 Cost estimate: ~{estimated_calls} LLM calls (approx. ${estimated_cost:.4f})")
                print(f"   Provider: {llm_provider.PROVIDER}, Max calls cap: {config.LLM_MAX_CALLS_PER_RUN}")
            
            print("Running LLM-assisted matcher on unresolved rows...")
            llm_matches, still_unresolved_website = resolve_unresolved_rows(unresolved_website, unresolved_gateway)
            llm_actually_ran = True
            print(f"  LLM resolved: {len(llm_matches)}  |  Still unresolved: {len(still_unresolved_website)}")

    all_matches = [
        {"website_id": m.website_id, "gateway_id": m.gateway_id,
         "confidence": m.confidence, "method": m.method, "reason": m.reason}
        for m in matched
    ] + llm_matches

    pd.DataFrame(all_matches).to_csv(os.path.join(args.output_dir, "matched_transactions.csv"), index=False)

    exceptions = pd.DataFrame({
        "website_id": still_unresolved_website["id"],
        "amount": still_unresolved_website["amount"],
        "date": still_unresolved_website["date"],
        "reason": "no confident match found (deterministic + LLM)",
    })
    exceptions.to_csv(os.path.join(args.output_dir, "exceptions.csv"), index=False)

    print(f"\nWrote {args.output_dir}/matched_transactions.csv ({len(all_matches)} rows)")
    print(f"Wrote {args.output_dir}/exceptions.csv ({len(exceptions)} rows)")
    if llm_actually_ran:
        print(f"Wrote {args.output_dir}/audit_log.jsonl (every LLM decision, with reasoning)")

    score_against_ground_truth(all_matches, args.ground_truth)


if __name__ == "__main__":
    main()
