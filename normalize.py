"""
Normalization layer.

Every source (website export, gateway export, marketplace export, etc.)
gets converted into the SAME shape before matching happens. This is what
makes the pipeline extensible to more sources later without rewriting
the matcher: add a new `load_and_normalize_X()` function that returns
a DataFrame with these columns, and the rest of the pipeline just works.

Common schema after normalization:
    id            - unique id from the source system
    date          - datetime.date
    amount        - float, rounded to 2 decimals
    reference     - lowercased, punctuation-stripped string
    source        - name of the originating system

Since this whole project exists to handle messy real-world exports, the
loaders here validate their input explicitly rather than letting pandas
raise a cryptic KeyError deep in some other function. A bad CSV should
fail loudly and clearly, right at the point it's read.
"""

import os
import re
import pandas as pd


PHONE_PATTERN = re.compile(r"\b\d{10}\b|\b\+?\d{1,3}[-\s]?\d{10}\b")


def redact_pii(text) -> str:
    """Redacts sequences that look like phone numbers from free-text
    reference fields before they're sent to an LLM or written to the
    audit log. Real-world payment reference text (especially from
    WhatsApp Commerce style flows) sometimes contains a customer's phone
    number typed directly into the note -- this should never leave the
    machine or land in a log file just because it happened to be in a
    payment reference."""
    if pd.isna(text):
        return text
    return PHONE_PATTERN.sub("[REDACTED-PHONE]", str(text))


def clean_reference(raw) -> str:
    """Lowercase and strip non-alphanumeric characters so 'INV-1002' and
    'inv1002pmt' become comparable tokens."""
    if pd.isna(raw):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(raw).lower())


def _read_csv_safely(path: str, required_columns: list) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Input file not found: {path}")

    df = pd.read_csv(path)

    if df.empty:
        raise ValueError(f"{path} has no rows -- nothing to reconcile.")

    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"{path} is missing required column(s): {missing}. "
            f"Found columns: {list(df.columns)}"
        )

    return df


def _validate_common_fields(df: pd.DataFrame, id_col: str, amount_col: str, source_name: str):
    """Checks that apply after normalization, regardless of source."""
    duplicate_ids = df[id_col][df[id_col].duplicated()].unique()
    if len(duplicate_ids) > 0:
        raise ValueError(
            f"{source_name}: duplicate id(s) found: {list(duplicate_ids)[:5]}"
            f"{' ...' if len(duplicate_ids) > 5 else ''}. "
            "Each transaction must have a unique id before reconciliation."
        )

    null_amounts = df[df[amount_col].isna()]
    if not null_amounts.empty:
        raise ValueError(
            f"{source_name}: {len(null_amounts)} row(s) have missing/unparseable amounts. "
            f"Affected ids: {list(null_amounts[id_col])[:5]}"
        )

    null_dates = df[df["date"].isna()]
    if not null_dates.empty:
        raise ValueError(
            f"{source_name}: {len(null_dates)} row(s) have missing/unparseable dates. "
            f"Affected ids: {list(null_dates[id_col])[:5]}"
        )


def load_website_orders(path: str) -> pd.DataFrame:
    df = _read_csv_safely(path, required_columns=["order_id", "order_date", "amount", "reference"])

    out = pd.DataFrame({
        "id": df["order_id"],
        "date": pd.to_datetime(df["order_date"], errors="coerce").dt.date,
        "amount": pd.to_numeric(df["amount"], errors="coerce").round(2),
        "reference": df["reference"].apply(clean_reference),
        "reference_raw": df["reference"].apply(redact_pii),
        "source": "website",
    })

    _validate_common_fields(out, id_col="id", amount_col="amount", source_name=path)
    return out


def load_gateway_settlement(path: str) -> pd.DataFrame:
    df = _read_csv_safely(path, required_columns=["settlement_id", "settle_date", "net_amount", "ref_no"])

    out = pd.DataFrame({
        "id": df["settlement_id"],
        # gateway exports commonly use dd/mm/yyyy -- dayfirst=True avoids silent misparsing
        "date": pd.to_datetime(df["settle_date"], dayfirst=True, errors="coerce").dt.date,
        "amount": pd.to_numeric(df["net_amount"], errors="coerce").round(2),
        "reference": df["ref_no"].apply(clean_reference),
        "reference_raw": df["ref_no"].apply(redact_pii),
        "fee": pd.to_numeric(df.get("gateway_fee", 0), errors="coerce").fillna(0),
        "source": "gateway",
    })

    _validate_common_fields(out, id_col="id", amount_col="amount", source_name=path)
    return out
