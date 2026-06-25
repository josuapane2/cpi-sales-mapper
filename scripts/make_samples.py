"""Create sample raw distributor files for local testing (tests/test_data).

The samples reference REAL product names from the imported master so that the
matcher resolves them and the end-to-end tests assert real values.
"""
import os
import pandas as pd

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TD = os.path.join(BASE, "tests", "test_data")
os.makedirs(TD, exist_ok=True)

# --- Format A: PT Panjunan internal (Fiesta, PCS, includes Draft) -> xlsx ---
# GT product codes (matched by code) + one Draft row that must be KEPT because
# Panjunan rule include_draft=true.
panjunan = pd.DataFrame([
    {"Date": "01/05/2026", "Status": "Posted", "SalesmanCode": "S01", "SalesmanName": "Budi",
     "CustomerCode": "C01", "CustomerName": "Toko Makmur", "ProductCode": "GT12010117",
     "ProductName": "FIESTA NUGGET HAPPY STAR 400 G", "TotalQuantity": 120},
    {"Date": "02/05/2026", "Status": "Draft", "SalesmanCode": "S01", "SalesmanName": "Budi",
     "CustomerCode": "C02", "CustomerName": "Toko Jaya", "ProductCode": "GT12010119",
     "ProductName": "FIESTA NUGGET CHEESE 123 400 G", "TotalQuantity": 24},
    {"Date": "03/05/2026", "Status": "Posted", "SalesmanCode": "S02", "SalesmanName": "Sari",
     "CustomerCode": "C03", "CustomerName": "Warung Bu Ida", "ProductCode": "GT18050102",
     "ProductName": "Fiesta RTG Bakso Keju 60G", "TotalQuantity": 144},
])
panjunan.to_excel(os.path.join(TD, "panjunan_bandung_may.xlsx"), index=False)

# --- Format B: external 'Laporan' name-only, KARTON -> csv (CPU) ---
# Tests: karton conversion, RTG type override for GT distributor, brand-aware
# fuzzy ('Naget'->'Nugget'), and an unmapped product.
cpu = pd.DataFrame([
    {"Nama_Customer": "UD Sinar", "Nama_Barang": "Fiesta Nugget Happy Star 400G", "Tgl": "2026-05-04", "Qty_Jual": 10},
    {"Nama_Customer": "UD Terang", "Nama_Barang": "Fiesta RTG Bakso Keju 60G", "Tgl": "2026-05-05", "Qty_Jual": 5},
    {"Nama_Customer": "Toko ABC", "Nama_Barang": "Champ Naget Ayam Kombinasi 450 G", "Tgl": "2026-05-06", "Qty_Jual": 3},
    {"Nama_Customer": "Toko XYZ", "Nama_Barang": "Produk Tidak Dikenal 999G", "Tgl": "2026-05-07", "Qty_Jual": 2},
])
cpu.to_csv(os.path.join(TD, "cpu_may.csv"), index=False)

# --- Format E: Panjunan RTG LBP, INNERBOX -> xlsx ---
rtg = pd.DataFrame([
    {"TGL": "2026-05-08", "PCODE": "GT16060119", "NAMA BARANG": "Fiesta RTG Siomay 54G",
     "NAMA CUSTOMER": "Kios Sosis", "innerbox": 6},
    {"TGL": "2026-05-09", "PCODE": "GT18050103", "NAMA BARANG": "Fiesta RTG Bakso BBQ 60G",
     "NAMA CUSTOMER": "Kios Bakar", "innerbox": 12},
])
rtg.to_excel(os.path.join(TD, "panjunan_rtg_may.xlsx"), index=False)

# --- Format F: MIXED PER-ROW UNIT (Satuan) -> xlsx ---------------------------
# A single file where each row carries its own 'Satuan'. Includes the synonym
# spellings CPI warned about: 'Box'/'Boks' = carton, 'Pak'/'Pack' = pcs, plus an
# RTG 'Inner Box' row. The same product appears in two units to prove that the
# unit (not a fixed file-level default) drives the conversion.
mixed = pd.DataFrame([
    # carton spelled normally -> 10 carton x 12 = 120 pcs ; 10 x 4.8 = 48 kg
    {"Tgl": "2026-05-10", "Nama Customer": "Toko Satu", "Kode": "GT12010117",
     "Nama Barang": "FIESTA NUGGET HAPPY STAR 400 G", "Qty": 10, "Satuan": "Carton"},
    # same product in PCS -> 24 pcs ; 24 x 0.4 = 9.6 kg
    {"Tgl": "2026-05-10", "Nama Customer": "Toko Dua", "Kode": "GT12010117",
     "Nama Barang": "FIESTA NUGGET HAPPY STAR 400 G", "Qty": 24, "Satuan": "Pcs"},
    # 'Box' must read as CARTON -> 5 carton x 12 = 60 pcs ; 5 x 5.4 = 27 kg
    {"Tgl": "2026-05-11", "Nama Customer": "Toko Tiga", "Kode": "",
     "Nama Barang": "Champ Naget Ayam Kombinasi 450 G", "Qty": 5, "Satuan": "Box"},
    # 'Pak' must read as PCS -> 30 pcs ; 30 x 0.45 = 13.5 kg
    {"Tgl": "2026-05-11", "Nama Customer": "Toko Empat", "Kode": "",
     "Nama Barang": "Champ Naget Ayam Kombinasi 450 G", "Qty": 30, "Satuan": "Pak"},
    # RTG 'Inner Box' -> 2 inner box x 12 = 24 pcs ; 2 x 0.72 = 1.44 kg
    {"Tgl": "2026-05-12", "Nama Customer": "Kios RTG", "Kode": "GT18050102",
     "Nama Barang": "Fiesta RTG Bakso Keju 60G", "Qty": 2, "Satuan": "Inner Box"},
    # 'Boks' synonym for carton on RTG -> 1 carton = 72 pcs ; 1 x 4.32 = 4.32 kg
    {"Tgl": "2026-05-12", "Nama Customer": "Kios RTG 2", "Kode": "GT18050102",
     "Nama Barang": "Fiesta RTG Bakso Keju 60G", "Qty": 1, "Satuan": "Boks"},
])
mixed.to_excel(os.path.join(TD, "mixed_units_may.xlsx"), index=False)

print("Samples written to", TD)
