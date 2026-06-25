"""Output validation checks (PRD 2.12 / 9.2)."""
from __future__ import annotations

from .rtg_detector import is_rtg, RTG_CATEGORY


def validate(rows):
    """Run validation checks over the list of output row dicts.

    Returns a dict with issue lists and counts.
    """
    issues = {
        "rtg_violations": [],
        "kg_inconsistent": [],
        "brand_mismatch": [],
        "duplicates": [],
        "unmapped": [],
    }

    seen = {}
    for i, row in enumerate(rows):
        name_dist = row.get("Nama Produk Dist", "")
        kategori = row.get("Kategori", "")

        # RTG validation: any RTG name must be Fiesta RTG
        if is_rtg(name_dist) and kategori != RTG_CATEGORY:
            issues["rtg_violations"].append({"row": i, "product": name_dist, "kategori": kategori})

        # KG consistency: Sum_KG ~= Qty_Kecil * Weight_perpcs (1% tolerance)
        try:
            qk = float(row.get("Qty Kecil", 0) or 0)
            wpp = float(row.get("Weight_perpcs", 0) or 0)
            skg = float(row.get("Sum_KG", 0) or 0)
            expected = qk * wpp
            if expected > 0 and abs(skg - expected) > 0.01 * expected:
                issues["kg_inconsistent"].append({"row": i, "expected": round(expected, 4), "got": skg})
        except (TypeError, ValueError):
            pass

        # Unmapped (no CPI code)
        if not str(row.get("Kode Produk CPI", "")).strip():
            issues["unmapped"].append({"row": i, "product": name_dist})

        # Duplicate detection key
        key = (row.get("Tgl Faktur"), row.get("Nama Toko"), row.get("Kode Produk CPI") or name_dist, row.get("Qty Kecil"))
        if key in seen:
            issues["duplicates"].append({"row": i, "first_seen": seen[key]})
        else:
            seen[key] = i

    summary = {k: len(v) for k, v in issues.items()}
    summary["total_rows"] = len(rows)
    return {"issues": issues, "summary": summary}
