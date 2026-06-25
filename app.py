"""CPI Sales Data Mapper - Streamlit web app (OPTIONAL / future phase).

Local development is done via cli.py (no Streamlit needed). This UI is kept for
later; to use it:  pip install -r requirements-app.txt  then  streamlit run app.py

Flow:  Upload -> Select Distributor -> Map Columns -> Settings ->
       Process & Validate -> Export (19-column XLSX).
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import streamlit as st

from mapper.loaders import (load_master, load_distributors, load_settings,
                            suggest_key, append_distributor)
from mapper.matcher import ProductMatcher
from mapper.engine import MappingEngine, apply_manual_mapping, OUTPUT_COLUMNS
from mapper.validator import validate
from utils.file_parser import read_file, auto_detect_columns, SYNONYMS
from utils.date_parser import make_normalizer
from utils.exporter import (to_xlsx_bytes, build_filename, split_by_month,
                            active_outlets_by_month)

BASE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = load_settings(os.path.join(BASE, "config", "settings.yaml"))
MASTER_PATH = os.path.join(BASE, SETTINGS["paths"]["master_product"])
DIST_PATH = os.path.join(BASE, SETTINGS["paths"]["distributors"])
# Prefer the new detailed pricelist (3 weight columns); fall back to the old one.
_RAW_CANDIDATES = [
    os.path.join(BASE, "data", "Master_AllProduct_detail.xlsx"),
    os.path.join(BASE, "data", "Master_AllProduct_Latest.xlsx"),
]
RAW_MASTER = next((p for p in _RAW_CANDIDATES if os.path.exists(p)), _RAW_CANDIDATES[0])


def ensure_master():
    """Auto-build the clean master from CPI's raw export if it doesn't exist yet.
    This means there is NO separate manual import step before launching."""
    if os.path.exists(MASTER_PATH):
        return
    if os.path.exists(RAW_MASTER):
        sys.path.insert(0, os.path.join(BASE, "scripts"))
        from import_master import import_master as _imp
        _imp(RAW_MASTER).to_excel(MASTER_PATH, index=False)

st.set_page_config(page_title="CPI Sales Data Mapper", page_icon="\U0001F9CA", layout="wide")


@st.cache_data(show_spinner=False)
def _load_master(path, mtime):
    return load_master(path)


@st.cache_data(show_spinner=False)
def _load_dists(path, mtime):
    return load_distributors(path)


def get_master():
    mtime = os.path.getmtime(MASTER_PATH) if os.path.exists(MASTER_PATH) else 0
    return _load_master(MASTER_PATH, mtime)


def get_dists():
    mtime = os.path.getmtime(DIST_PATH) if os.path.exists(DIST_PATH) else 0
    return _load_dists(DIST_PATH, mtime)


ss = st.session_state
ss.setdefault("step", 1)
ss.setdefault("raw_df", None)
ss.setdefault("detected", {})
ss.setdefault("out_df", None)
ss.setdefault("report", None)

# ----------------------------------------------------------------------------
st.title("\U0001F9CA CPI Sales Data Mapper")
st.caption("Transform raw distributor sales files into the standard 19-column format.")

ensure_master()
if not os.path.exists(MASTER_PATH):
    st.error("Product master not found. Put CPI's 'Master_AllProduct_Latest.xlsx' "
             "into the data/ folder (it builds automatically on launch).")
    st.stop()

master = get_master()
dists = get_dists()
matcher = ProductMatcher(master)
engine = MappingEngine(matcher)

with st.sidebar:
    st.header("Progress")
    steps = ["1. Upload", "2. Distributor", "3. Map Columns", "4. Settings",
             "5. Process", "6. Export"]
    for i, label in enumerate(steps, start=1):
        st.write(("\u2705 " if ss.step > i else ("\u27A1\uFE0F " if ss.step == i else "\u2B1C ")) + label)
    st.divider()
    st.metric("Products in master", len(master))
    st.metric("Distributor templates", len(dists))

# --- STEP 1: UPLOAD ---------------------------------------------------------
st.subheader("1. Upload File")
uploaded = st.file_uploader("Drag & drop or browse (.xlsx, .xls, .csv)",
                            type=["xlsx", "xls", "csv"])
header_row = st.number_input("Header row (0-indexed)", min_value=0, value=0, step=1)
skip_rows = st.number_input("Rows to skip before header", min_value=0, value=0, step=1)

if uploaded is not None:
    try:
        df = read_file(uploaded, header_row=int(header_row), skip_rows=int(skip_rows))
        df = df.fillna("")
        ss.raw_df = df
        ss.detected = auto_detect_columns(df)
        st.success(f"Loaded {len(df)} rows \u00d7 {len(df.columns)} columns.")
        st.dataframe(df.head(10), use_container_width=True)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read file: {exc}")

# --- STEP 2: DISTRIBUTOR ----------------------------------------------------
if ss.raw_df is not None:
    st.subheader("2. Select Distributor")
    NEW_KEY = "__new__"
    keys = list(dists.keys())
    labels = {k: dists[k]["distributor"]["name"] for k in keys}
    options = [NEW_KEY] + keys
    sel = st.selectbox(
        "Distributor", options,
        format_func=lambda k: "\u2795 Create new distributor\u2026" if k == NEW_KEY else labels[k],
    )
    creating = (sel == NEW_KEY)
    TYPE_OPTS = ["Dist. GT", "Dist. Fiesta", "Dist. RTG", "Dist. GT & Dist. RTG"]

    if creating:
        st.markdown("**New distributor details**")
        n1, n2 = st.columns(2)
        new_name = n1.text_input("Distributor name", key="nd_name",
                                 placeholder="PT Contoh Distributor")
        new_alias = n2.text_input("Alias (used in the output file name)", key="nd_alias",
                                  placeholder="CTH")
        n3, n4, n5 = st.columns(3)
        new_cabang = n3.text_input("Cabang", key="nd_cabang")
        new_area = n4.text_input("Area", key="nd_area")
        new_type = n5.selectbox("Type", TYPE_OPTS, key="nd_type")
        new_draft = st.checkbox("Include draft / unposted orders", value=False, key="nd_draft")
        template = {
            "distributor": {
                "name": new_name.strip() or "New Distributor",
                "alias": new_alias.strip() or "NEW",
                "cabang": new_cabang.strip(),
                "area": new_area.strip(),
                "type": new_type,
            },
            "file": {"format": "xlsx", "header_row": int(header_row), "skip_rows": int(skip_rows)},
            "columns": {},  # rely on auto-detect + the manual mapping below
            "rules": {"rtg_detect": "name", "include_draft": new_draft},
        }
        st.caption("Confirm the column mapping in step 3 and the quantity unit in "
                   "step 4. You can optionally save this distributor to the list "
                   "for next time (in step 4).")
    else:
        template = dists[sel]
        d = template["distributor"]
        c1, c2, c3 = st.columns(3)
        c1.info(f"**Cabang:** {d.get('cabang','')}")
        c2.info(f"**Area:** {d.get('area','')}")
        c3.info(f"**Type:** {d.get('type','')}")

    # --- STEP 3: COLUMN MAPPING --------------------------------------------
    st.subheader("3. Map Columns")
    st.caption("Auto-detected from headers. Override any field below.")
    file_cols = [""] + list(ss.raw_df.columns)
    fields = ["date", "sku_name", "sku_code", "qty", "unit", "customer",
              "customer_code", "salesman_code", "salesman_name", "area", "status"]
    overrides = {}
    grid = st.columns(2)
    for i, field in enumerate(fields):
        default = ss.detected.get(field) or template.get("columns", {}).get(field, "")
        if default not in file_cols:
            default = ""
        idx = file_cols.index(default) if default in file_cols else 0
        label = field.replace("_", " ").title()
        if field in ss.detected:
            label += "  \u2705"
        overrides[field] = grid[i % 2].selectbox(label, file_cols, index=idx, key=f"map_{field}")

    # --- STEP 4: SETTINGS ---------------------------------------------------
    st.subheader("4. Settings")
    s1, s2 = st.columns(2)
    default_unit = template.get("columns", {}).get("qty_unit", "pcs")
    unit_opts = ["pcs", "karton", "innerbox"]
    overrides["qty_unit"] = s1.radio("Default Quantity Unit", unit_opts,
                                     index=unit_opts.index(default_unit) if default_unit in unit_opts else 0,
                                     horizontal=True)
    if overrides.get("unit"):
        s1.caption("\u2139\uFE0F A 'Satuan' column is mapped \u2014 each row uses its own "
                   "unit; this default only applies to rows with a blank/unknown unit.")
    dayfirst = s2.checkbox("Date is day-first (DD/MM/YYYY)", value=True)

    # Optional: persist a newly-created distributor to config for future runs
    if creating:
        with st.expander("\U0001F4BE Save this distributor to the list for next time"):
            st.caption("Writes it to config/distributors.yaml so it appears in the "
                       "dropdown on future runs, with the column mapping and unit you set above.")
            if st.button("Save distributor to config"):
                try:
                    save_cols = {f: overrides[f] for f in fields if overrides.get(f)}
                    save_cols["qty_unit"] = overrides.get("qty_unit", "pcs")
                    save_template = {
                        "distributor": template["distributor"],
                        "file": {"format": "xlsx", "header_row": int(header_row),
                                 "skip_rows": int(skip_rows)},
                        "columns": save_cols,
                        "rules": template["rules"],
                    }
                    new_key = append_distributor(
                        DIST_PATH,
                        suggest_key(template["distributor"]["alias"], dists),
                        save_template,
                    )
                    st.success(f"Saved as '{new_key}'. It's now in the distributor list.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not save: {exc}")

    # --- STEP 5: PROCESS ---------------------------------------------------
    st.subheader("5. Process & Validate")
    if st.button("\u2699\uFE0F Process", type="primary"):
        normalizer = make_normalizer(dayfirst=dayfirst)
        out_df, report = engine.process(ss.raw_df, template, overrides=overrides,
                                         date_normalizer=normalizer)
        ss.out_df = out_df
        ss.report = report
        ss.sel = sel

    if ss.out_df is not None:
        report = ss.report
        out_df = ss.out_df
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Rows", report["total_rows"])
        m2.metric("Total KG", f"{report['total_kg']:,.1f}")
        m3.metric("Unmapped", report["unmapped_count"])
        m4.metric("Draft skipped", report["skipped_draft"])

        v = validate(out_df.to_dict("records"))
        if v["summary"]["rtg_violations"]:
            st.error(f"RTG violations: {v['summary']['rtg_violations']} (must be 0)")
        else:
            st.success("RTG validation passed \u2014 all RTG products categorized as Fiesta RTG.")
        if v["summary"]["kg_inconsistent"]:
            st.warning(f"KG consistency issues: {v['summary']['kg_inconsistent']}")
        if v["summary"]["duplicates"]:
            st.warning(f"Potential duplicate rows: {v['summary']['duplicates']}")

        cc1, cc2 = st.columns(2)
        if report["by_brand"]:
            cc1.write("**KG by Brand**")
            cc1.dataframe(pd.DataFrame(report["by_brand"].items(), columns=["Brand", "KG"]),
                          use_container_width=True, hide_index=True)
        if report["by_kategori"]:
            cc2.write("**KG by Kategori**")
            cc2.dataframe(pd.DataFrame(report["by_kategori"].items(), columns=["Kategori", "KG"]),
                          use_container_width=True, hide_index=True)

        # Active outlets per month (distinct customer code, else customer name)
        outlets = active_outlets_by_month(out_df)
        if not outlets.empty:
            st.write("**Active Outlets by Month**")
            st.caption("Distinct outlets per month (by Kode Toko, or Nama Toko when the code is blank).")
            months_only = outlets[outlets["Month"] != "TOTAL (distinct)"]
            oc1, oc2 = st.columns([2, 1])
            oc1.dataframe(outlets, use_container_width=True, hide_index=True)
            if not months_only.empty:
                oc2.bar_chart(months_only.set_index("Month")["Active Outlets"])

        # Manual mapping of unmapped products
        if report["unmapped_products"]:
            st.warning("Unmapped products \u2014 assign manually below, then re-apply.")
            sap_opts = [""] + [f"{r['SAP_Code']} | {r['ProductName']}" for r in master]
            manual = {}
            for name, count in report["unmapped_products"]:
                pick = st.selectbox(f"{name}  (\u00d7{count})", sap_opts, key=f"mm_{name}")
                if pick:
                    manual[name] = pick.split(" | ", 1)[0]
            if manual and st.button("Apply manual mappings"):
                ss.out_df = apply_manual_mapping(out_df, matcher, manual)
                st.rerun()

        st.write("**Preview (first 20 rows)**")
        st.dataframe(out_df.head(20), use_container_width=True)

        # --- STEP 6: EXPORT -------------------------------------------------
        st.subheader("6. Export")
        alias = template["distributor"].get("alias", "Dist")
        split = st.checkbox("Split into one file per month", value=True)
        if split:
            for month, sub in split_by_month(out_df):
                fname = build_filename(alias, month)
                st.download_button(f"\u2B07\uFE0F {fname}  ({len(sub)} rows)",
                                   data=to_xlsx_bytes(sub), file_name=fname,
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                   key=f"dl_{month}")
        else:
            fname = build_filename(alias, "All")
            st.download_button(f"\u2B07\uFE0F {fname}", data=to_xlsx_bytes(out_df),
                               file_name=fname,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
