# CPI Sales Data Mapper

Local tool that transforms raw sales reports from 20+ distributors into a
standardized **19-column** unified format for PT. Citra Pratama Indotama (CPI).

Built per the PRD (`PRD_WebMapper_FrozenFood.md`). **Current phase: local
development** — driven by a command-line interface (`cli.py`), no web server
required. A Streamlit UI (`app.py`) is included for later but is optional.

The product master uses CPI's real export `Master_AllProduct_detail.xlsx`
(193 products, 7 brands, 8 categories, 13 RTG products) which carries **three
per-unit weight columns**: `weight_kg/carton`, `weight_kg/inner_box` (RTG only),
`weight_kg/pcs`. Prices are intentionally not used at this stage.

---

## 1. Install (one time)

Requires Python 3.10+.

```bash
cd cpimapper
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` is light: pandas, openpyxl, PyYAML (no Streamlit).

## 2. Import the product master

CPI's real file lives at `data/Master_AllProduct_Latest.xlsx`. Convert it to the
clean master the app reads (`data/master_product.xlsx`):

```bash
python scripts/import_master.py
```

The importer reads only the `master_PL` sheet (ignores the price-list sheet),
skips the section separators, and keeps the 9 columns: `SAP_Code, ProductName,
Carton_pcs, weight_kg_carton, weight_kg_innerbox, weight_kg_pcs, GT_Code, Brand,
Category`. (Older 2-weight exports still import — missing per-unit weights are
derived from `Carton_pcs`.) When CPI sends an updated export, replace that file
and re-run this command.

## 3. Use the CLI (local development)

```bash
# list the 22 distributor templates
python cli.py list

# inspect a raw file: auto-detected columns + preview
python cli.py inspect tests/test_data/cpu_may.csv

# process a raw file with a chosen distributor template
python cli.py process tests/test_data/cpu_may.csv --dist CPU --preview 10
python cli.py process raw.xlsx --dist PANJUNAN_BANDUNG --unit pcs --out output
```

`process` writes one 19-column `.xlsx` per month into `output/`
(e.g. `CPU_2026-05_Mapped.xlsx`) and prints a summary + validation report
(RTG violations, KG consistency, duplicates, unmapped products).

Useful flags: `--unit pcs|karton|innerbox`, `--no-split` (one combined file),
`--month-first` (MM/DD/YYYY dates), `--header N`, `--skip N`.

### Mixed quantity units per row (Satuan)

Many distributors record one row in cartons and the next in pieces. Instead of
converting by hand, map the file's **Satuan (unit) column** and the engine reads
the unit *per row*:

- In the file, you need two things side by side: the **quantity** (`Qty`) and the
  **unit** (`Satuan`). Each row is then weighed with the matching master column:
  `carton -> weight_kg/carton`, `pcs -> weight_kg/pcs`,
  `inner_box -> weight_kg/inner_box` (RTG).
- The Satuan column is auto-detected (headers like *Satuan, UOM, Unit,
  Kemasan*). You can also pin it in a template via `columns: { unit: "Satuan" }`.
- Synonyms are handled automatically:
  - **carton** = carton, karton, ctn, dus, kardus, **box**, **boks**, dos
  - **pcs** = pcs, pc, **pack**, **pak**, pck, bungkus, bks, sachet
  - **inner_box** = inner box, innerbox, inner, ib (RTG only)
- `--unit` / the "Default Quantity Unit" setting is now only a **fallback** for
  rows where the Satuan cell is blank or unrecognized (or files with no Satuan
  column at all).

## 4. Run the tests

```bash
python scripts/make_samples.py     # regenerate sample raw files (optional)
python tests/test_engine.py        # 11 end-to-end checks
```

Tests run against the real master and derive expected weights from it, covering:
19-column schema, RTG category forcing, type precedence (Panjunan vs RTG vs GT),
PCS/KARTON/INNERBOX conversion, KG calculation, draft handling, brand-aware
fuzzy matching, unmapped detection, and zero RTG violations.

---

## 5. Business rules implemented

- **RTG detection (absolute):** any product whose name contains "RTG" or
  "Ready To Go" is forced to category **Fiesta RTG** and never matched to a
  non-RTG product. (`mapper/rtg_detector.py`)
- **Type Distributor priority:** PT Panjunan (internal) -> `Dist. Fiesta` for all
  rows; otherwise RTG rows -> `Dist. RTG`; otherwise `Dist. GT`.
- **Per-row unit (Satuan):** each row converts by its own unit when a Satuan
  column is present; synonyms (box/boks->carton, pack/pak->pcs) are normalized.
  (`mapper/units.py`)
- **Quantity conversion:** PCS / KARTON / INNERBOX (1 box = 12 pcs, 1 carton =
  6 box = 72 pcs). (`mapper/calculator.py`)
- **Weight (Sum_KG):** raw quantity x the master weight matching the row's unit
  (`weight_kg_carton` / `weight_kg_innerbox` / `weight_kg_pcs`).
- **Draft orders:** kept only for PT Panjunan internal (`include_draft: true`).
- **Product matching priority:** SAP code -> GT code -> exact name ->
  RTG-restricted -> brand-aware normalized fuzzy -> manual fallback.
  (`mapper/matcher.py`)
- **Validation:** RTG categorization, KG consistency (1% tolerance), duplicates,
  unmapped products. (`mapper/validator.py`)

---

## 6. Adding a new distributor

Edit `config/distributors.yaml` and add a block (copy an existing one). Set
`distributor` metadata, `columns` mapping guesses, `qty_unit`, and `rules`.
Auto-detect + the `inspect` command help you confirm header differences per file.

---

## 7. Project structure

```
cpimapper/
  cli.py                 # >>> local command-line interface (primary)
  app.py                 # optional Streamlit UI (needs requirements-app.txt)
  requirements.txt       # core deps (pandas/openpyxl/pyyaml)
  requirements-app.txt   # optional: + streamlit
  config/
    distributors.yaml     # 22 distributor templates
    settings.yaml
  data/
    Master_AllProduct_detail.xlsx  # CPI's real export w/ 3 weight cols (source)
    master_product.xlsx            # clean master (generated by import_master)
    templates/
  mapper/
    units.py             # Satuan (unit) synonym normalization
    engine.py            # core transformation -> 19 columns
    matcher.py           # product matching (SAP/GT/name/fuzzy)
    calculator.py        # qty + KG calculations
    validator.py         # validation checks
    rtg_detector.py      # RTG detection
    loaders.py           # master / template / settings loaders
  utils/
    file_parser.py       # read xlsx/csv + column auto-detect
    date_parser.py       # date normalization (ISO-aware)
    exporter.py          # 19-column XLSX export, split by month
  scripts/
    import_master.py     # convert CPI master -> clean master_product.xlsx
    make_samples.py      # generate sample raw files
  tests/
    test_engine.py       # end-to-end tests
    test_data/           # sample raw distributor files
```

---

## 8. Output schema (19 columns, in order)

`Cabang, Area, Type Distributor, Nama Distributor, Kode Salesman, Nama Salesman,
Tgl Faktur, Kode Toko, Nama Toko, Kode Produk Dist, Nama Produk Dist, Qty Kecil,
Qty Karton, Kode Produk CPI, Nama Produk Cpi, Weight_perpcs, Sum_KG, Brand,
Kategori`

(`Qty Kecil` = total pieces, `Qty Karton` = cartons, `Weight_perpcs` = per-piece
weight, `Sum_KG` = total weight computed from each row's own unit.)

*Built per PRD v1.0 (June 2026). Local-development phase.*
