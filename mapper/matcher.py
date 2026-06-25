"""Product name matching against the CPI master product database (PRD section 8).

Match priority:
  1. Direct SAP code match (strip GT- prefix)
  2. RTG keyword override (restrict candidate pool to RTG products)
  3. Exact name match (normalized)
  4. Name-normalization fuzzy match (token overlap + weight/gram hint)
  5. Manual fallback (returns None -> listed as unmapped)
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .rtg_detector import is_rtg

# Spelling / vocabulary normalizations (PRD 8.2)
_REPLACEMENTS = [
    (r"\bnaget\b", "nugget"),
    (r"\bchiscken\b", "chicken"),
    (r"\bstikie\b", "stick"),
    (r"\bstik\b", "stick"),
    (r"\bgf\.?\b", "golden fiesta"),
    (r"\bsosis\b", "sausage"),
    (r"\bmt\b", ""),  # strip MT prefix
]

_BRANDS = [
    "golden fiesta", "fiesta", "champ", "okey", "asimo", "akumo", "amogi",
]

_GRAM_RE = re.compile(r"(\d+)\s*(?:gr|gram|g)\b", re.IGNORECASE)
_PACK_RE = re.compile(r"x\s*(\d+)\b", re.IGNORECASE)


def normalize(name: str) -> str:
    if not name:
        return ""
    s = str(name).lower()
    s = s.replace(".", " ")
    for pat, rep in _REPLACEMENTS:
        s = re.sub(pat, rep, s)
    # collapse non-alphanumeric
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def strip_brand(norm_name: str) -> str:
    s = norm_name
    for b in _BRANDS:
        s = s.replace(b, " ")
    return re.sub(r"\s+", " ", s).strip()


def detect_brand(norm_name: str):
    """Return the brand string found in a normalized name, or '' if none.
    Checks multi-word brands first (e.g. 'golden fiesta' before 'fiesta')."""
    for b in _BRANDS:  # _BRANDS is ordered longest-first
        if b in norm_name:
            return b
    return ""


def extract_gram(name: str):
    m = _GRAM_RE.search(str(name))
    return int(m.group(1)) if m else None


def strip_gt_prefix(code: str) -> str:
    if code is None:
        return ""
    c = str(code).strip().upper()
    c = re.sub(r"^GT[-_ ]?", "", c)
    return c.strip()


class ProductMatcher:
    """Wraps the master product list and resolves raw product names/codes."""

    def __init__(self, master_records):
        """master_records: list of dicts with keys SAP_Code, ProductName,
        Carton_pcs, kg_per_pack, weight_per_pcs, GT_Code, Brand, Category."""
        self.records = []
        self.by_sap = {}
        self.by_gt = {}
        self.by_norm = {}
        for r in master_records:
            rec = dict(r)
            sap = str(rec.get("SAP_Code", "")).strip()
            gt = str(rec.get("GT_Code", "")).strip().upper()
            norm = normalize(rec.get("ProductName", ""))
            rec["_norm"] = norm
            rec["_norm_nobrand"] = strip_brand(norm)
            rec["_gram"] = extract_gram(rec.get("ProductName", ""))
            rec["_is_rtg"] = is_rtg(rec.get("ProductName", "")) or \
                str(rec.get("Category", "")).strip().lower() in ("ready to go", "fiesta rtg", "rtg")
            self.records.append(rec)
            if sap:
                self.by_sap[sap] = rec
            if gt:
                self.by_gt[gt] = rec
            if norm and norm not in self.by_norm:
                self.by_norm[norm] = rec
        self.rtg_records = [r for r in self.records if r["_is_rtg"]]

    # -- individual strategies -------------------------------------------
    def _match_by_code(self, code):
        if not code:
            return None
        raw = str(code).strip().upper()
        if raw in self.by_gt:
            return self.by_gt[raw]
        sap = strip_gt_prefix(code)
        if sap in self.by_sap:
            return self.by_sap[sap]
        if raw in self.by_sap:
            return self.by_sap[raw]
        return None

    def _fuzzy(self, norm_query, pool, gram=None):
        best, best_score = None, 0.0
        q_nobrand = strip_brand(norm_query)
        q_tokens = set(q_nobrand.split())
        q_brand = detect_brand(norm_query)
        for rec in pool:
            cand = rec["_norm_nobrand"]
            c_tokens = set(cand.split())
            if not c_tokens or not q_tokens:
                continue
            overlap = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
            ratio = SequenceMatcher(None, q_nobrand, cand).ratio()
            score = 0.6 * overlap + 0.4 * ratio
            # gram bonus
            if gram and rec.get("_gram") == gram:
                score += 0.15
            elif gram and rec.get("_gram") and rec["_gram"] != gram:
                score -= 0.10
            # brand awareness: prefer same brand, penalize a brand mismatch
            if q_brand:
                rec_brand = str(rec.get("Brand", "")).strip().lower()
                if rec_brand == q_brand:
                    score += 0.20
                elif rec_brand:
                    score -= 0.25
            if score > best_score:
                best, best_score = rec, score
        return best, best_score

    # -- main entry -------------------------------------------------------
    def match(self, product_name, product_code=None, fuzzy_threshold=0.55):
        """Return (record_or_None, method_str, confidence_float)."""
        name = product_name or ""
        rtg = is_rtg(name)

        # 1. direct code match
        rec = self._match_by_code(product_code)
        if rec is not None:
            # Respect RTG override: if the raw name says RTG, only accept an RTG record.
            if rtg and not rec["_is_rtg"]:
                pass  # fall through to RTG-restricted matching
            else:
                return rec, "sap_code", 1.0

        norm = normalize(name)
        gram = extract_gram(name)

        # 2 + 3. RTG override restricts the candidate pool to RTG products only
        if rtg:
            if norm in self.by_norm and self.by_norm[norm]["_is_rtg"]:
                return self.by_norm[norm], "exact_name_rtg", 1.0
            best, score = self._fuzzy(norm, self.rtg_records, gram)
            if best is not None and score >= fuzzy_threshold:
                return best, "rtg_fuzzy", round(score, 3)
            # RTG but unmatched -> return None; engine still forces Fiesta RTG category.
            return None, "rtg_unmatched", 0.0

        # 3. exact name match (non-RTG)
        if norm in self.by_norm:
            return self.by_norm[norm], "exact_name", 1.0

        # 4. normalized fuzzy match across all products
        best, score = self._fuzzy(norm, self.records, gram)
        if best is not None and score >= fuzzy_threshold:
            return best, "fuzzy", round(score, 3)

        # 5. manual fallback
        return None, "unmapped", 0.0
