"""Import CPI's master product file -> clean data/master_product.xlsx.

The current export is `Master_AllProduct_detail.xlsx` (sheet `master_PL`):
  - blank first row, real headers on the 2nd row,
  - brand/category section-separator rows (no SAP code) mixed between products,
  - THREE weight columns:
        weight_kg/carton    (all products)
        weight_kg/inner_box (RTG products only; 0 otherwise)
        weight_kg/pcs       (all products)

This script keeps only valid product rows and writes the 9 standard columns:
  SAP_Code, ProductName, Carton_pcs,
  weight_kg_carton, weight_kg_innerbox, weight_kg_pcs,
  GT_Code, Brand, Category

It is tolerant of the older 2-weight export (kg/pack + weight/pcs(RTG)) so old
files still import: missing per-unit weights are derived from Carton_pcs.

Usage:
  python scripts/import_master.py [SOURCE_XLSX]
"""
import os
import sys

import pandas as pd

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Prefer the new detailed pricelist; fall back to the older export name.
_CANDIDATES = [
    os.path.join(BASE, "data", "Master_AllProduct_detail.xlsx"),
    os.path.join(BASE, "data", "Master_AllProduct_Latest.xlsx"),
]
DEFAULT_SRC = next((p for p in _CANDIDATES if os.path.exists(p)), _CANDIDATES[0])
OUT = os.path.join(BASE, "data", "master_product.xlsx")

# real header name (lower-cased, stripped) -> standard column name
RENAME = {
    "sap-code": "SAP_Code", "sap code": "SAP_Code", "sap_code": "SAP_Code",
    "productname": "ProductName", "product name": "ProductName",
    "carton/pcs": "Carton_pcs", "carton pcs": "Carton_pcs", "carton_pcs": "Carton_pcs",
    "weight_kg/carton": "weight_kg_carton", "weight kg/carton": "weight_kg_carton",
    "weight_kg_carton": "weight_kg_carton", "weight/carton": "weight_kg_carton",
    "weight_kg/inner_box": "weight_kg_innerbox", "weight_kg/innerbox": "weight_kg_innerbox",
    "weight kg/inner box": "weight_kg_innerbox", "weight_kg_innerbox": "weight_kg_innerbox",
    "weight/inner_box": "weight_kg_innerbox",
    "weight_kg/pcs": "weight_kg_pcs", "weight kg/pcs": "weight_kg_pcs",
    "weight_kg_pcs": "weight_kg_pcs", "weight/pcs": "weight_kg_pcs",
    "gt-code": "GT_Code", "gt code": "GT_Code", "gt_code": "GT_Code",
    "brand": "Brand", "category": "Category",
    # legacy 2-weight export
    "kg/pack": "kg_per_pack", "weight/pcs(rtg)": "weight_per_pcs_legacy",
}

OUT_COLS = ["SAP_Code", "ProductName", "Carton_pcs",
            "weight_kg_carton", "weight_kg_innerbox", "weight_kg_pcs",
            "GT_Code", "Brand", "Category"]


def _num(v):
    s = str(v).strip().replace(",", ".")
    if s in ("", "nan", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_header_row(src, sheet):
    """Locate the row index that contains the 'SAP' header (handles blank rows)."""
    probe = pd.read_excel(src, sheet_name=sheet, header=None, dtype=str, nrows=10).fillna("")
    for i in range(len(probe)):
        joined = " ".join(str(x).lower() for x in probe.iloc[i].values)
        if "sap" in joined and ("product" in joined or "brand" in joined):
            return i
    return 1


def import_master(src=DEFAULT_SRC, sheet="master_PL", header_row=None):
    if header_row is None:
        header_row = _find_header_row(src, sheet)
    df = pd.read_excel(src, sheet_name=sheet, header=header_row, dtype=str)
    df = df.rename(columns=lambda c: RENAME.get(str(c).strip().lower(), str(c).strip()))

    # keep only rows with a numeric SAP code (drops section separators / blanks)
    sap = df.get("SAP_Code", pd.Series(dtype=str)).astype(str).str.strip()
    df = df[sap.str.match(r"^\d{5,}$", na=False)].copy()

    out = pd.DataFrame()
    out["SAP_Code"] = df["SAP_Code"].astype(str).str.strip()
    out["ProductName"] = df["ProductName"].astype(str).str.strip()
    out["Carton_pcs"] = df.get("Carton_pcs", "").map(_num)

    # Per-unit weights. Prefer explicit columns; derive any that are missing.
    has_pcs = "weight_kg_pcs" in df.columns
    has_carton = "weight_kg_carton" in df.columns
    has_ib = "weight_kg_innerbox" in df.columns
    legacy_pack = df.get("kg_per_pack")
    legacy_rtg = df.get("weight_per_pcs_legacy")

    w_pcs, w_carton, w_ib = [], [], []
    for idx in range(len(df)):
        row = df.iloc[idx]
        cpcs = _num(row.get("Carton_pcs", 0)) if "Carton_pcs" in df.columns else 0.0
        pcs = _num(row.get("weight_kg_pcs")) if has_pcs else 0.0
        carton = _num(row.get("weight_kg_carton")) if has_carton else 0.0
        ib = _num(row.get("weight_kg_innerbox")) if has_ib else 0.0

        # legacy fallbacks: kg/pack is per-pcs for non-RTG, weight/pcs(RTG) per-pcs for RTG
        if pcs <= 0 and legacy_rtg is not None and _num(row.get("weight_per_pcs_legacy")) > 0:
            pcs = _num(row.get("weight_per_pcs_legacy"))
        if pcs <= 0 and legacy_pack is not None:
            pcs = _num(row.get("kg_per_pack"))
        if carton <= 0 and pcs > 0 and cpcs > 0:
            carton = round(pcs * cpcs, 6)
        # inner box only meaningful for RTG (72 pcs/carton, 6 boxes) -> 12 pcs/box
        if ib <= 0 and carton > 0 and cpcs == 72:
            ib = round(carton / 6.0, 6)
        w_pcs.append(pcs)
        w_carton.append(carton)
        w_ib.append(ib)

    out["weight_kg_carton"] = w_carton
    out["weight_kg_innerbox"] = w_ib
    out["weight_kg_pcs"] = w_pcs
    out["GT_Code"] = df.get("GT_Code", "").astype(str).str.strip()
    out["Brand"] = df.get("Brand", "").astype(str).str.strip()
    out["Category"] = df.get("Category", "").astype(str).str.strip()
    out = out[OUT_COLS].reset_index(drop=True)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SRC
    out = import_master(src)
    rtg = (out["weight_kg_innerbox"] > 0).sum()
    out.to_excel(OUT, index=False)
    print(f"Imported {len(out)} products from {os.path.basename(src)} -> {OUT}")
    print(f"  Brands: {sorted(out['Brand'].unique())}")
    print(f"  Categories: {sorted(out['Category'].unique())}")
    print(f"  RTG products (inner_box weight > 0): {rtg}")


if __name__ == "__main__":
    main()
