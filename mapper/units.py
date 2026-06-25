"""Quantity-unit (Satuan) normalization.

Distributors record the selling unit per row in many ways. We collapse them to
three canonical units used by the calculator:

  "carton"   - a full carton/box        (synonyms: karton, ctn, dus, box, boks, kardus, krt)
  "innerbox" - an RTG inner box (12 pcs) (synonyms: inner box, innerbox, inner, ib)
  "pcs"      - a single piece           (synonyms: pieces, pc, pack, pak, pck, bungkus, bks)

NOTE (per CPI): some distributors write "carton" as "box"/"boks" and "pcs" as
"pack"/"pak". So bare "box" -> carton, while "inner box" -> innerbox.
"""
from __future__ import annotations

import re

CARTON = "carton"
INNERBOX = "innerbox"
PCS = "pcs"

# Checked in order. Inner-box patterns MUST come before the generic box->carton
# rule, otherwise "inner box" would be misread as a carton.
_RULES = [
    (INNERBOX, re.compile(r"\b(inner[\s_-]*box(?:es)?|innerbox|inner|ib|in\.?box)\b", re.I)),
    (CARTON, re.compile(r"\b(cartons?|cartoon|karton|ctn|crt|krt|dus|kardus|box(?:es)?|boks|bok|dos)\b", re.I)),
    (PCS, re.compile(r"\b(pcs|pieces?|pc|pack(?:s)?|pak|pck|pkt|bungkus|bks|sachet|satuan|pices)\b", re.I)),
]


def normalize_unit(raw, default=None):
    """Return one of carton|innerbox|pcs for a raw 'satuan' value.

    Returns `default` when the value is empty or unrecognized.
    """
    if raw is None:
        return default
    s = str(raw).strip().lower()
    if not s or s in ("nan", "none"):
        return default
    # already canonical
    if s in (CARTON, INNERBOX, PCS):
        return s
    for unit, pat in _RULES:
        if pat.search(s):
            return unit
    return default
