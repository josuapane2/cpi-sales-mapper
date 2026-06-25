"""End-to-end validation of the mapping engine against sample files.

Uses the REAL imported master (data/master_product.xlsx). Expected weights are
derived from the master itself, so the tests stay valid if the master changes.

Run:  python tests/test_engine.py    (or)    python -m pytest tests/test_engine.py
"""
import os
import sys

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BASE)

from mapper.loaders import (load_master, load_distributors,
                            suggest_key, append_distributor)
from mapper.matcher import ProductMatcher
from mapper.engine import MappingEngine, OUTPUT_COLUMNS
from mapper.validator import validate
from mapper.units import normalize_unit
from utils.file_parser import read_file, auto_detect_columns
from utils.date_parser import make_normalizer
from utils.exporter import active_outlets_by_month
import pandas as pd

MASTER = load_master(os.path.join(BASE, "data", "master_product.xlsx"))
DISTS = load_distributors(os.path.join(BASE, "config", "distributors.yaml"))
MATCHER = ProductMatcher(MASTER)
ENGINE = MappingEngine(MATCHER)
TD = os.path.join(BASE, "tests", "test_data")

# quick lookup of master rows by SAP code
BY_SAP = {str(r["SAP_Code"]).strip(): r for r in MASTER}


def _run(fname, dist_key):
    df = read_file(os.path.join(TD, fname)).fillna("")
    detected = auto_detect_columns(df)
    template = DISTS[dist_key]
    return ENGINE.process(df, template, overrides=dict(detected),
                          date_normalizer=make_normalizer(dayfirst=True))


def test_master_imported():
    assert len(MASTER) >= 150, "real master should have ~193 products"
    rtg = [r for r in MASTER if float(r.get("weight_kg_innerbox") or 0) > 0]
    assert len(rtg) == 13, f"expected 13 RTG products, got {len(rtg)}"
    # every product must carry a per-carton and per-pcs weight
    assert all(float(r["weight_kg_carton"]) > 0 for r in MASTER)
    assert all(float(r["weight_kg_pcs"]) > 0 for r in MASTER)


def test_unit_synonyms():
    assert normalize_unit("Carton") == "carton"
    assert normalize_unit("karton") == "carton"
    assert normalize_unit("Box") == "carton"
    assert normalize_unit("Boks") == "carton"
    assert normalize_unit("DUS") == "carton"
    assert normalize_unit("Pcs") == "pcs"
    assert normalize_unit("Pak") == "pcs"
    assert normalize_unit("Pack") == "pcs"
    assert normalize_unit("Inner Box") == "innerbox"
    assert normalize_unit("innerbox") == "innerbox"
    assert normalize_unit("", default="pcs") == "pcs"
    assert normalize_unit("weird", default="carton") == "carton"


def test_19_columns():
    out, _ = _run("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG")
    assert list(out.columns) == OUTPUT_COLUMNS, "Output must have exactly the 19 columns"


def test_panjunan_draft_kept_and_fiesta_type():
    out, rep = _run("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG")
    assert rep["skipped_draft"] == 0      # include_draft=true for Panjunan
    assert len(out) == 3
    assert "Dist. Fiesta" in set(out["Type Distributor"])


def test_rtg_forced_category_panjunan():
    # Panjunan -> type forced to 'Dist. Fiesta'; RTG CATEGORY override still absolute.
    out, _ = _run("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG")
    r = out[out["Kode Produk CPI"] == "18050102"].iloc[0]
    assert r["Kategori"] == "Fiesta RTG"
    assert r["Type Distributor"] == "Dist. Fiesta"
    wpp = float(BY_SAP["18050102"]["weight_kg_pcs"])  # 0.06 per pcs
    assert abs(float(r["Sum_KG"]) - 144 * wpp) < 0.001, r["Sum_KG"]  # 144 pcs


def test_rtg_type_override_for_gt_distributor():
    out, _ = _run("cpu_may.csv", "CPU")
    r = out[out["Kode Produk CPI"] == "18050102"].iloc[0]
    assert r["Kategori"] == "Fiesta RTG"
    assert r["Type Distributor"] == "Dist. RTG"
    carton = float(BY_SAP["18050102"]["Carton_pcs"])         # 72
    w_carton = float(BY_SAP["18050102"]["weight_kg_carton"])  # 4.32
    assert int(r["Qty Kecil"]) == int(5 * carton)            # 5 karton -> 360 pcs
    assert abs(float(r["Sum_KG"]) - 5 * w_carton) < 0.001, r["Sum_KG"]


def test_pcs_conversion_nonrtg():
    out, _ = _run("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG")
    r = out[out["Kode Produk CPI"] == "12010117"].iloc[0]
    carton = float(BY_SAP["12010117"]["Carton_pcs"])     # 12
    w_pcs = float(BY_SAP["12010117"]["weight_kg_pcs"])   # 0.4
    assert int(r["Qty Kecil"]) == 120
    assert abs(float(r["Qty Karton"]) - 120 / carton) < 0.001   # 10
    assert abs(float(r["Sum_KG"]) - 120 * w_pcs) < 0.001         # 48


def test_karton_conversion_and_unmapped():
    out, rep = _run("cpu_may.csv", "CPU")
    assert len(out) == 4
    assert rep["unmapped_count"] == 1                  # 'Produk Tidak Dikenal'
    nug = out[out["Kode Produk CPI"] == "12010117"].iloc[0]
    carton = float(BY_SAP["12010117"]["Carton_pcs"])
    w_carton = float(BY_SAP["12010117"]["weight_kg_carton"])
    assert int(nug["Qty Kecil"]) == int(10 * carton)   # 120
    assert abs(float(nug["Sum_KG"]) - 10 * w_carton) < 0.001


def test_brand_aware_fuzzy_match():
    # 'Champ Naget Ayam Kombinasi 450 G' must map to a CHAMP product, not FIESTA.
    out, _ = _run("cpu_may.csv", "CPU")
    champ = out[out["Nama Produk Dist"].str.contains("Champ", case=False)].iloc[0]
    assert champ["Brand"] == "CHAMP", champ.to_dict()


def test_innerbox_conversion():
    out, _ = _run("panjunan_rtg_may.xlsx", "PANJUNAN_RTG")
    r = out[out["Kode Produk CPI"] == "16060119"].iloc[0]
    assert int(r["Qty Kecil"]) == 72        # 6 innerbox * 12
    assert abs(float(r["Qty Karton"]) - 1.0) < 0.001   # 6 / 6
    w_ib = float(BY_SAP["16060119"]["weight_kg_innerbox"])  # 0.648
    assert abs(float(r["Sum_KG"]) - 6 * w_ib) < 0.001       # 3.888
    assert r["Kategori"] == "Fiesta RTG"


# --- PER-ROW UNIT (Satuan) ---------------------------------------------------

def test_mixed_units_per_row():
    """Each row in mixed_units_may.xlsx must convert by its OWN Satuan value."""
    out, rep = _run("mixed_units_may.xlsx", "MIXED_DEMO")
    assert len(out) == 6
    # auto-detect + template should have found a unit column -> mixed counts
    assert set(rep["unit_counts"]) == {"carton", "pcs", "innerbox"}, rep["unit_counts"]

    rows = out.to_dict("records")

    # Row 1: 10 carton of Happy Star (carton_pcs 12) -> 120 pcs, 10*4.8 = 48 kg
    r = rows[0]
    assert int(r["Qty Kecil"]) == 120 and abs(float(r["Qty Karton"]) - 10) < 0.001
    assert abs(float(r["Sum_KG"]) - 48.0) < 0.01, r["Sum_KG"]

    # Row 2: same product, 24 PCS -> 24 pcs, 24*0.4 = 9.6 kg
    r = rows[1]
    assert int(r["Qty Kecil"]) == 24
    assert abs(float(r["Sum_KG"]) - 9.6) < 0.01, r["Sum_KG"]

    # Row 3: 'Box' must be CARTON -> Champ 5 carton (x12) -> 60 pcs, 5*5.4 = 27 kg
    r = rows[2]
    assert r["Brand"] == "CHAMP"
    assert int(r["Qty Kecil"]) == 60
    assert abs(float(r["Sum_KG"]) - 27.0) < 0.01, r["Sum_KG"]

    # Row 4: 'Pak' must be PCS -> Champ 30 pcs, 30*0.45 = 13.5 kg
    r = rows[3]
    assert int(r["Qty Kecil"]) == 30
    assert abs(float(r["Sum_KG"]) - 13.5) < 0.01, r["Sum_KG"]

    # Row 5: 'Inner Box' RTG -> 2 inner box (x12) -> 24 pcs, 2*0.72 = 1.44 kg
    r = rows[4]
    assert r["Kategori"] == "Fiesta RTG"
    assert int(r["Qty Kecil"]) == 24
    assert abs(float(r["Sum_KG"]) - 1.44) < 0.01, r["Sum_KG"]

    # Row 6: 'Boks' = carton on RTG -> 1 carton (72 pcs), 1*4.32 = 4.32 kg
    r = rows[5]
    assert int(r["Qty Kecil"]) == 72
    assert abs(float(r["Sum_KG"]) - 4.32) < 0.01, r["Sum_KG"]


def test_dist_A_single_column_fixed_unit():
    """Distributor A style: ONE quantity column, no Satuan column.

    All rows use the distributor's default unit (CPU -> karton). This proves the
    single-column case still works exactly like before.
    """
    out, rep = _run("cpu_may.csv", "CPU")
    # no unit column present -> every row resolved to the default 'carton'
    assert set(rep["unit_counts"]) == {"carton"}, rep["unit_counts"]
    nug = out[out["Kode Produk CPI"] == "12010117"].iloc[0]
    carton = float(BY_SAP["12010117"]["Carton_pcs"])
    w_carton = float(BY_SAP["12010117"]["weight_kg_carton"])
    assert int(nug["Qty Kecil"]) == int(10 * carton)
    assert abs(float(nug["Sum_KG"]) - 10 * w_carton) < 0.001


def test_unit_autodetect_is_safe():
    """Auto-detect finds a real Satuan column but ignores lookalikes."""
    # Distributor B: a genuine Satuan column is detected.
    df_b = pd.DataFrame(columns=["Tanggal", "Nama Barang", "Qty", "Satuan",
                                 "Unit Price", "Nama Customer"])
    det = auto_detect_columns(df_b)
    assert det.get("unit") == "Satuan", det
    assert det.get("qty") == "Qty", det

    # 'UOM' header is recognized too.
    df_uom = pd.DataFrame(columns=["Tgl", "Nama", "Quantity", "UOM"])
    assert auto_detect_columns(df_uom).get("unit") == "UOM"

    # Distributor A: only a 'Unit Price' column -> must NOT be taken as unit.
    df_a = pd.DataFrame(columns=["Tgl", "Nama Barang", "Karton", "Unit Price"])
    assert auto_detect_columns(df_a).get("unit") is None, "price column misread as unit"


def test_mixed_units_kg_consistent():
    out, _ = _run("mixed_units_may.xlsx", "MIXED_DEMO")
    v = validate(out.to_dict("records"))
    assert v["summary"]["kg_inconsistent"] == 0, v["issues"]["kg_inconsistent"]
    assert v["summary"]["rtg_violations"] == 0


def test_suggest_key_unique():
    existing = {"CTH": {}, "CTH_2": {}}
    assert suggest_key("PT Contoh!", {}) == "PT_CONTOH".replace(" ", "_")
    assert suggest_key("CTH", existing) == "CTH_3"
    assert suggest_key("", {}) == "NEW_DIST"


def test_append_distributor_roundtrip():
    import tempfile, shutil
    src = os.path.join(BASE, "config", "distributors.yaml")
    tmp = tempfile.mktemp(suffix=".yaml")
    shutil.copy(src, tmp)
    before = load_distributors(tmp)
    tpl = {
        "distributor": {"name": "PT Test Dist", "alias": "TST",
                         "cabang": "Sumatra", "area": "Medan", "type": "Dist. GT"},
        "file": {"format": "xlsx", "header_row": 0, "skip_rows": 0},
        "columns": {"date": "Tanggal", "sku_name": "Nama Barang", "qty": "Qty",
                    "customer": "Toko", "qty_unit": "karton", "sku_code": ""},
        "rules": {"rtg_detect": "name", "include_draft": False},
    }
    key = suggest_key("TST", before)
    append_distributor(tmp, key, tpl)
    after = load_distributors(tmp)
    assert key in after and key not in before
    saved = after[key]
    assert saved["distributor"]["cabang"] == "Sumatra"
    assert saved["distributor"]["type"] == "Dist. GT"
    assert saved["columns"]["qty_unit"] == "karton"
    assert "sku_code" not in saved["columns"]   # blank values are dropped
    # original templates are still intact (comments/blocks preserved)
    assert len(after) == len(before) + 1
    os.remove(tmp)


def test_active_outlets_by_month():
    """Distinct outlets per month, by code (else name), with a grand total."""
    df = pd.DataFrame([
        # May: codes C01, C02, C01(repeat) -> 2 distinct
        {"Tgl Faktur": "2026-05-01", "Kode Toko": "C01", "Nama Toko": "Toko A"},
        {"Tgl Faktur": "2026-05-02", "Kode Toko": "C02", "Nama Toko": "Toko B"},
        {"Tgl Faktur": "2026-05-15", "Kode Toko": "C01", "Nama Toko": "Toko A"},
        # June: C02 again + a blank-code row -> falls back to Nama Toko
        {"Tgl Faktur": "2026-06-03", "Kode Toko": "C02", "Nama Toko": "Toko B"},
        {"Tgl Faktur": "2026-06-04", "Kode Toko": "", "Nama Toko": "Toko C"},
    ])
    res = active_outlets_by_month(df)
    by_month = dict(zip(res["Month"], res["Active Outlets"]))
    assert by_month["2026-05"] == 2          # C01, C02
    assert by_month["2026-06"] == 2          # C02, Toko C (name fallback)
    # TOTAL distinct across months = C01, C02, Toko C
    assert by_month["TOTAL (distinct)"] == 3


def test_active_outlets_on_real_output():
    out, _ = _run("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG")
    res = active_outlets_by_month(out)
    # sample has 3 distinct customers, all in May 2026
    row = res[res["Month"] == "2026-05"]
    assert len(row) == 1 and int(row.iloc[0]["Active Outlets"]) == 3


def test_no_rtg_violations():
    for fname, key in [("panjunan_bandung_may.xlsx", "PANJUNAN_BANDUNG"),
                       ("cpu_may.csv", "CPU"), ("panjunan_rtg_may.xlsx", "PANJUNAN_RTG"),
                       ("mixed_units_may.xlsx", "MIXED_DEMO")]:
        out, _ = _run(fname, key)
        v = validate(out.to_dict("records"))
        assert v["summary"]["rtg_violations"] == 0, (fname, v["summary"])


def _main():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
    print(f"\nAll {len(fns)} tests passed.")


if __name__ == "__main__":
    _main()
