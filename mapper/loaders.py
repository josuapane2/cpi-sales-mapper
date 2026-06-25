"""Loaders for the master product database and distributor templates."""
from __future__ import annotations

import os

import pandas as pd
import yaml

# Standard clean-master columns. Weights are now per-unit (kg):
#   weight_kg_carton   - weight of one carton
#   weight_kg_innerbox - weight of one inner box (RTG only; 0 otherwise)
#   weight_kg_pcs      - weight of one piece
MASTER_COLUMNS = [
    "SAP_Code", "ProductName", "Carton_pcs",
    "weight_kg_carton", "weight_kg_innerbox", "weight_kg_pcs",
    "GT_Code", "Brand", "Category",
]

# Tolerant header aliases so masters with slightly different headers still load.
_MASTER_ALIASES = {
    "sap_code": "SAP_Code", "sap code": "SAP_Code", "sap-code": "SAP_Code", "kode": "SAP_Code", "kode cpi": "SAP_Code",
    "productname": "ProductName", "product name": "ProductName", "nama produk": "ProductName", "nama": "ProductName",
    "carton_pcs": "Carton_pcs", "carton/pcs": "Carton_pcs", "pcs per carton": "Carton_pcs", "isi": "Carton_pcs",
    "weight_kg_carton": "weight_kg_carton", "weight_kg/carton": "weight_kg_carton", "weight kg/carton": "weight_kg_carton", "weight/carton": "weight_kg_carton",
    "weight_kg_innerbox": "weight_kg_innerbox", "weight_kg/inner_box": "weight_kg_innerbox", "weight_kg/innerbox": "weight_kg_innerbox", "weight kg/inner box": "weight_kg_innerbox", "weight/inner_box": "weight_kg_innerbox",
    "weight_kg_pcs": "weight_kg_pcs", "weight_kg/pcs": "weight_kg_pcs", "weight kg/pcs": "weight_kg_pcs", "weight/pcs": "weight_kg_pcs",
    # legacy 2-weight export
    "kg_per_pack": "kg_per_pack", "kg/pack": "kg_per_pack", "kg per pack": "kg_per_pack",
    "weight_per_pcs": "weight_per_pcs_legacy", "weight/pcs(rtg)": "weight_per_pcs_legacy",
    "gt_code": "GT_Code", "gt code": "GT_Code", "gt-code": "GT_Code", "kode gt": "GT_Code",
    "brand": "Brand", "merk": "Brand",
    "category": "Category", "kategori": "Category",
}


def _num(v):
    s = str(v).strip().replace(",", ".")
    if not s or s.lower() in ("nan", "none"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_master(path):
    """Load master product xlsx/csv into a list of normalized dict records.

    Each record carries the three per-unit weights. If the file is an older
    2-weight export, the per-unit weights are derived from Carton_pcs so the
    rest of the engine keeps working.
    """
    if str(path).lower().endswith(".csv"):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(path, dtype=str)
    df = df.fillna("")
    rename = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in _MASTER_ALIASES:
            rename[col] = _MASTER_ALIASES[key]
    df = df.rename(columns=rename)

    records = []
    for _, r in df.iterrows():
        carton_pcs = _num(r.get("Carton_pcs", 0))
        w_pcs = _num(r.get("weight_kg_pcs", 0))
        w_carton = _num(r.get("weight_kg_carton", 0))
        w_ib = _num(r.get("weight_kg_innerbox", 0))

        # Legacy fallbacks (older master with kg_per_pack / weight_per_pcs).
        if w_pcs <= 0:
            legacy_rtg = _num(r.get("weight_per_pcs_legacy", 0))
            legacy_pack = _num(r.get("kg_per_pack", 0))
            w_pcs = legacy_rtg if legacy_rtg > 0 else legacy_pack
        if w_carton <= 0 and w_pcs > 0 and carton_pcs > 0:
            w_carton = round(w_pcs * carton_pcs, 6)
        if w_ib <= 0 and w_carton > 0 and carton_pcs == 72:
            w_ib = round(w_carton / 6.0, 6)

        records.append({
            "SAP_Code": str(r.get("SAP_Code", "")).strip(),
            "ProductName": str(r.get("ProductName", "")).strip(),
            "Carton_pcs": carton_pcs,
            "weight_kg_carton": w_carton,
            "weight_kg_innerbox": w_ib,
            "weight_kg_pcs": w_pcs,
            "GT_Code": str(r.get("GT_Code", "")).strip(),
            "Brand": str(r.get("Brand", "")).strip(),
            "Category": str(r.get("Category", "")).strip(),
        })
    return records


def load_distributors(path):
    """Load distributor templates yaml -> dict keyed by template id."""
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("distributors", {})


import re as _re


def suggest_key(alias, existing):
    """Turn an alias into a unique UPPERCASE template key not in `existing`."""
    base = _re.sub(r"[^A-Za-z0-9]+", "_", str(alias or "")).strip("_").upper()
    base = base or "NEW_DIST"
    keys = set(existing or [])
    if base not in keys:
        return base
    i = 2
    while f"{base}_{i}" in keys:
        i += 1
    return f"{base}_{i}"


def _flow(d):
    """Render a flat dict as a YAML flow mapping, e.g. {a: "x", b: 0, c: true}."""
    parts = []
    for k, v in d.items():
        if isinstance(v, bool):
            sv = "true" if v else "false"
        elif isinstance(v, (int, float)):
            sv = str(v)
        else:
            sv = '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'
        parts.append(f"{k}: {sv}")
    return "{" + ", ".join(parts) + "}"


def append_distributor(path, key, template):
    """Append a new distributor block to distributors.yaml (preserves comments).

    `template` must have keys: distributor, file, columns, rules.
    Returns the key written. Raises ValueError if the key already exists.
    """
    existing = load_distributors(path)
    if key in existing:
        raise ValueError(f"Distributor key '{key}' already exists")
    dist = template.get("distributor", {})
    fil = template.get("file", {"format": "xlsx", "header_row": 0, "skip_rows": 0})
    cols = {k: v for k, v in template.get("columns", {}).items() if v not in (None, "")}
    rules = template.get("rules", {"rtg_detect": "name", "include_draft": False})
    block = (
        f"\n  {key}:\n"
        f"    distributor: {_flow(dist)}\n"
        f"    file: {_flow(fil)}\n"
        f"    columns: {_flow(cols)}\n"
        f"    rules: {_flow(rules)}\n"
    )
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + block)
    return key


def load_settings(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)
