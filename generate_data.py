"""
Generates two synthetic CSVs simulating a D2C seller's data:
  - website_orders.csv   : orders placed on the seller's own website
  - gateway_settlement.csv : payment gateway settlement report (bank side)

Also writes ground_truth.csv so the pipeline's accuracy can be measured
honestly against a known answer key, instead of eyeballing results.

Deliberate messiness injected (mirrors real gateway exports):
  - reference number formatting differs between systems
  - gateway fee deducted from settlement amount
  - a few date lags (order date vs settlement date)
  - a few genuine non-matches (refunds, test orders)
"""

import random
import os
import pandas as pd
from datetime import datetime, timedelta

random.seed(42)

os.makedirs("data", exist_ok=True)

NUM_CLEAN = 30      # straightforward matches
NUM_MESSY = 15       # matches, but need normalization/fuzzy logic
NUM_UNRESOLVED = 8   # ambiguous, likely need the LLM step
NUM_NOMATCH = 5      # genuine non-matches (refund, cancelled, duplicate)

START_DATE = datetime(2026, 7, 1)

website_rows = []
gateway_rows = []
ground_truth = []  # (order_id, settlement_ref, is_match, note)

order_counter = 1000


def rand_date(base, spread_days=0):
    return base + timedelta(days=random.randint(0, spread_days))


# ---- Clean matches: same amount, reference maps directly, small date lag ----
for i in range(NUM_CLEAN):
    order_id = f"ORD-{order_counter}"
    amount = round(random.uniform(299, 4999), 2)
    order_date = rand_date(START_DATE, 20)
    settle_date = order_date + timedelta(days=random.choice([1, 2, 3]))
    ref = f"INV{order_counter}"

    website_rows.append({"order_id": order_id, "order_date": order_date.strftime("%Y-%m-%d"),
                          "amount": amount, "reference": ref, "customer": f"cust{order_counter}"})
    gateway_rows.append({"settlement_id": f"STL-{order_counter}", "settle_date": settle_date.strftime("%d/%m/%Y"),
                          "net_amount": amount, "ref_no": ref, "gateway_fee": 0.0})
    ground_truth.append((order_id, f"STL-{order_counter}", True, "clean match"))
    order_counter += 1

# ---- Messy matches: fee deducted, reference format differs, needs fuzzy/tolerance logic ----
for i in range(NUM_MESSY):
    order_id = f"ORD-{order_counter}"
    amount = round(random.uniform(299, 4999), 2)
    fee = round(amount * 0.02, 2)  # 2% gateway fee
    net_amount = round(amount - fee, 2)
    order_date = rand_date(START_DATE, 20)
    settle_date = order_date + timedelta(days=random.choice([2, 3, 4]))
    ref = f"INV{order_counter}"
    # gateway stores reference messily: lowercase, dashes, extra text
    messy_ref = f"inv-{order_counter}-pmt"

    website_rows.append({"order_id": order_id, "order_date": order_date.strftime("%Y-%m-%d"),
                          "amount": amount, "reference": ref, "customer": f"cust{order_counter}"})
    gateway_rows.append({"settlement_id": f"STL-{order_counter}", "settle_date": settle_date.strftime("%d/%m/%Y"),
                          "net_amount": net_amount, "ref_no": messy_ref, "gateway_fee": fee})
    ground_truth.append((order_id, f"STL-{order_counter}", True, "fee-adjusted + fuzzy ref match"))
    order_counter += 1

# ---- Unresolved / ambiguous: reference missing or garbled, amount close but not exact ----
for i in range(NUM_UNRESOLVED):
    order_id = f"ORD-{order_counter}"
    amount = round(random.uniform(299, 4999), 2)
    fee = round(amount * random.uniform(0.015, 0.03), 2)
    net_amount = round(amount - fee, 2)
    order_date = rand_date(START_DATE, 20)
    settle_date = order_date + timedelta(days=random.choice([3, 4, 5, 6]))
    # reference is dropped or replaced with customer name only -- forces LLM reasoning
    garbled_ref = f"payment for {random.choice(['order', 'purchase'])} #{order_counter % 100}"

    website_rows.append({"order_id": order_id, "order_date": order_date.strftime("%Y-%m-%d"),
                          "amount": amount, "reference": f"INV{order_counter}", "customer": f"cust{order_counter}"})
    gateway_rows.append({"settlement_id": f"STL-{order_counter}", "settle_date": settle_date.strftime("%d/%m/%Y"),
                          "net_amount": net_amount, "ref_no": garbled_ref, "gateway_fee": fee})
    ground_truth.append((order_id, f"STL-{order_counter}", True, "ambiguous ref, needs reasoning"))
    order_counter += 1

# ---- Genuine non-matches: refunds / cancelled orders / duplicate settlement noise ----
for i in range(NUM_NOMATCH):
    order_id = f"ORD-{order_counter}"
    amount = round(random.uniform(299, 4999), 2)
    order_date = rand_date(START_DATE, 20)

    # order exists on website but was cancelled -- no settlement should match it
    website_rows.append({"order_id": order_id, "order_date": order_date.strftime("%Y-%m-%d"),
                          "amount": amount, "reference": f"INV{order_counter}", "customer": f"cust{order_counter}"})
    ground_truth.append((order_id, None, False, "cancelled order, no settlement expected"))

    # a stray settlement with no corresponding website order (e.g. duplicate payout, adjustment)
    stray_amount = round(random.uniform(299, 4999), 2)
    gateway_rows.append({"settlement_id": f"STL-{order_counter}", "settle_date": order_date.strftime("%d/%m/%Y"),
                          "net_amount": stray_amount, "ref_no": "adjustment", "gateway_fee": 0.0})
    ground_truth.append((None, f"STL-{order_counter}", False, "stray settlement adjustment, no order"))
    order_counter += 1

# Shuffle rows so order doesn't leak the answer
random.shuffle(website_rows)
random.shuffle(gateway_rows)

pd.DataFrame(website_rows).to_csv("data/website_orders.csv", index=False)
pd.DataFrame(gateway_rows).to_csv("data/gateway_settlement.csv", index=False)
pd.DataFrame(ground_truth, columns=["order_id", "settlement_id", "is_match", "note"]).to_csv(
    "data/ground_truth.csv", index=False)

print(f"Generated {len(website_rows)} website orders and {len(gateway_rows)} settlement rows.")
print("Files written to data/website_orders.csv, data/gateway_settlement.csv, data/ground_truth.csv")
