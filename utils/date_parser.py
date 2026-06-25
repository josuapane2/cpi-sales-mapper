"""Date format detection & normalization to YYYY-MM-DD."""
from __future__ import annotations

import re

import pandas as pd

# Unambiguous ISO date like 2026-05-04 or 2026/05/04 -> never apply dayfirst.
_ISO_RE = re.compile(r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}")


def normalize_date(value, dayfirst=True, fmt=None):
    """Return an ISO date string 'YYYY-MM-DD' or '' if unparseable.

    dayfirst defaults True because Indonesian distributor files commonly use
    DD/MM/YYYY.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str) and not value.strip():
        return ""
    try:
        if fmt:
            ts = pd.to_datetime(value, format=fmt, errors="coerce")
        elif isinstance(value, str) and _ISO_RE.match(value):
            # ISO ordering is year-month-day; dayfirst must not reorder it.
            ts = pd.to_datetime(value, dayfirst=False, errors="coerce")
        else:
            ts = pd.to_datetime(value, dayfirst=dayfirst, errors="coerce")
        if pd.isna(ts):
            return str(value)
        return ts.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(value)


def make_normalizer(dayfirst=True, fmt=None):
    def _n(v):
        return normalize_date(v, dayfirst=dayfirst, fmt=fmt)
    return _n


def extract_month(iso_date):
    """Return 'YYYY-MM' for an ISO date string, or '' if invalid."""
    if not iso_date or len(str(iso_date)) < 7:
        return ""
    return str(iso_date)[:7]
