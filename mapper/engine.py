"""Core transformation engine: raw distributor file -> 19-column unified output."""
from __future__ import annotations

import pandas as pd

from .matcher import ProductMatcher
from .calculator import convert_qty, weight_for_unit
from .units import normalize_unit, PCS
from .rtg_detector import is_rtg, RTG_CATEGORY, RTG_TYPE

# The canonical 19-column output schema (PRD section 3), in order.
OUTPUT_COLUMNS = [
    "Cabang",
    "Area",
    "Type Distributor",
    "Nama Distributor",
    "Kode Salesman",
    "Nama Salesman",
    "Tgl Faktur",
    "Kode Toko",
    "Nama Toko",
    "Kode Produk Dist",
    "Nama Produk Dist",
    "Qty Kecil",
    "Qty Karton",
    "Kode Produk CPI",
    "Nama Produk Cpi",
    "Weight_perpcs",
    "Sum_KG",
    "Brand",
    "Kategori",
]

DRAFT_TOKENS = {"draft", "drafted", "draf"}


def _get(row, colname):
    if not colname:
        return ""
    if colname in row and pd.notna(row[colname]):
        return row[colname]
    return ""


def _resolve_type(template, row_is_rtg):
    """Determine per-row Type Distributor.

    Priority (PRD 1.3 + 7.3):
      1. PT Panjunan internal Fiesta distributor -> always "Dist. Fiesta".
      2. RTG product row -> "Dist. RTG".
      3. Otherwise the distributor's own type (default "Dist. GT").
    """
    base_type = str(template.get("distributor", {}).get("type", "Dist. GT"))
    if "fiesta" in base_type.lower() and "rtg" not in base_type.lower():
        return "Dist. Fiesta"
    if row_is_rtg:
        return RTG_TYPE
    if "gt" in base_type.lower():
        return "Dist. GT"
    return base_type


class MappingEngine:
    def __init__(self, matcher: ProductMatcher):
        self.matcher = matcher

    def process(self, df: pd.DataFrame, template: dict, overrides: dict | None = None,
                date_normalizer=None):
        """Transform a raw dataframe into the 19-column output.

        df         : raw distributor dataframe (headers already set)
        template   : distributor template dict (see config/distributors.yaml)
        overrides  : optional dict overriding template["columns"] mappings + qty_unit
        date_normalizer: optional callable(value) -> 'YYYY-MM-DD'

        Returns (output_df, report_dict).
        """
        cols = dict(template.get("columns", {}))
        if overrides:
            cols.update({k: v for k, v in overrides.items() if v})

        dist = template.get("distributor", {})
        # Default unit used when a row has no Satuan value (or no Satuan column).
        default_unit = normalize_unit(
            (overrides or {}).get("qty_unit") or cols.get("qty_unit"), default=PCS)
        # Optional per-row unit column (Satuan). When present, each row converts
        # by its own unit; the default above is only the fallback.
        unit_col = cols.get("unit")
        rules = template.get("rules", {})
        include_draft = bool(rules.get("include_draft", False))
        area_mapping = template.get("area_mapping", {}) or {}

        date_col = cols.get("date")
        name_col = cols.get("sku_name")
        code_col = cols.get("sku_code")
        qty_col = cols.get("qty")
        cust_col = cols.get("customer")
        cust_code_col = cols.get("customer_code")
        sman_code_col = cols.get("salesman_code")
        sman_name_col = cols.get("salesman_name")
        area_col = cols.get("area")
        status_col = cols.get("status")

        out_rows = []
        unmapped = {}
        match_methods = {}
        unit_counts = {}
        skipped_draft = 0

        for _, row in df.iterrows():
            prod_name = str(_get(row, name_col)).strip()
            if not prod_name:
                continue

            # Draft filter: include only for internal Fiesta (Panjunan) per rule.
            if status_col and not include_draft:
                status_val = str(_get(row, status_col)).strip().lower()
                if status_val in DRAFT_TOKENS:
                    skipped_draft += 1
                    continue

            prod_code = str(_get(row, code_col)).strip() if code_col else ""
            qty_raw = _get(row, qty_col)

            # Per-row unit (Satuan): read the row's own unit, else the default.
            row_unit = normalize_unit(_get(row, unit_col), default=default_unit) if unit_col else default_unit
            unit_counts[row_unit] = unit_counts.get(row_unit, 0) + 1

            rec, method, conf = self.matcher.match(prod_name, prod_code)
            row_is_rtg = is_rtg(prod_name) or (rec is not None and rec.get("_is_rtg"))

            match_methods[method] = match_methods.get(method, 0) + 1
            if rec is None and not row_is_rtg:
                unmapped[prod_name] = unmapped.get(prod_name, 0) + 1
            elif rec is None and row_is_rtg:
                unmapped[prod_name] = unmapped.get(prod_name, 0) + 1

            carton_pcs = rec.get("Carton_pcs") if rec else 0
            # RTG cartons hold 72 pcs when master lacks the value.
            if row_is_rtg and (not carton_pcs or float(carton_pcs or 0) == 0):
                carton_pcs = 72
            qty_kecil, qty_karton = convert_qty(qty_raw, row_unit, carton_pcs)

            # Sum_KG = raw qty * the master weight matching this row's unit.
            wpp, sum_kg = weight_for_unit(qty_raw, row_unit, rec, row_is_rtg)

            # Category: RTG override is absolute.
            if row_is_rtg:
                kategori = RTG_CATEGORY
            else:
                kategori = str(rec.get("Category", "")) if rec else ""
            brand = str(rec.get("Brand", "")) if rec else ("FIESTA" if row_is_rtg else "")

            raw_area = str(_get(row, area_col)).strip() if area_col else ""
            area = area_mapping.get(raw_area, raw_area) if raw_area else dist.get("area", "")

            date_val = _get(row, date_col)
            if date_normalizer:
                date_val = date_normalizer(date_val)

            out_rows.append({
                "Cabang": dist.get("cabang", ""),
                "Area": area,
                "Type Distributor": _resolve_type(template, row_is_rtg),
                "Nama Distributor": dist.get("name", ""),
                "Kode Salesman": str(_get(row, sman_code_col)).strip(),
                "Nama Salesman": str(_get(row, sman_name_col)).strip(),
                "Tgl Faktur": date_val,
                "Kode Toko": str(_get(row, cust_code_col)).strip(),
                "Nama Toko": str(_get(row, cust_col)).strip(),
                "Kode Produk Dist": prod_code,
                "Nama Produk Dist": prod_name,
                "Qty Kecil": qty_kecil,
                "Qty Karton": qty_karton,
                "Kode Produk CPI": str(rec.get("SAP_Code", "")) if rec else "",
                "Nama Produk Cpi": str(rec.get("ProductName", "")) if rec else "",
                "Weight_perpcs": wpp,
                "Sum_KG": sum_kg,
                "Brand": brand,
                "Kategori": kategori,
            })

        out_df = pd.DataFrame(out_rows, columns=OUTPUT_COLUMNS)

        report = {
            "total_rows": len(out_df),
            "total_kg": round(float(out_df["Sum_KG"].sum()) if not out_df.empty else 0.0, 2),
            "unmapped_products": sorted(unmapped.items(), key=lambda x: -x[1]),
            "unmapped_count": len(unmapped),
            "match_methods": match_methods,
            "unit_counts": unit_counts,
            "skipped_draft": skipped_draft,
            "by_brand": out_df.groupby("Brand")["Sum_KG"].sum().round(2).to_dict() if not out_df.empty else {},
            "by_kategori": out_df.groupby("Kategori")["Sum_KG"].sum().round(2).to_dict() if not out_df.empty else {},
        }
        return out_df, report


def apply_manual_mapping(out_df, matcher, manual_map):
    """Apply user manual product assignments.

    manual_map: { raw_product_name: SAP_Code }
    Recomputes CPI fields + weights for affected rows.
    """
    if not manual_map:
        return out_df
    df = out_df.copy()
    for idx, row in df.iterrows():
        raw = row["Nama Produk Dist"]
        if raw in manual_map:
            rec = matcher.by_sap.get(str(manual_map[raw]).strip())
            if rec is None:
                continue
            row_is_rtg = bool(rec.get("_is_rtg")) or row["Kategori"] == RTG_CATEGORY
            # Qty Kecil is already in pieces, so weigh per-pcs to stay consistent.
            qty_kecil = float(row["Qty Kecil"] or 0)
            wpp, sum_kg = weight_for_unit(qty_kecil, PCS, rec, row_is_rtg)
            df.at[idx, "Kode Produk CPI"] = str(rec.get("SAP_Code", ""))
            df.at[idx, "Nama Produk Cpi"] = str(rec.get("ProductName", ""))
            df.at[idx, "Brand"] = str(rec.get("Brand", ""))
            df.at[idx, "Kategori"] = RTG_CATEGORY if row_is_rtg else str(rec.get("Category", ""))
            df.at[idx, "Weight_perpcs"] = wpp
            df.at[idx, "Sum_KG"] = sum_kg
    return df
