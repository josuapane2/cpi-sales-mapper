"""Read various raw distributor file formats + column auto-detection."""
from __future__ import annotations

import io
import re

import pandas as pd

# Header-name synonyms used for auto-detecting the standard fields.
SYNONYMS = {
    "date": ["tgl faktur", "tgl inv", "tgl invoice", "tgl", "tanggal transaksi",
             "tanggal", "date", "invoice date", "order date"],
    "sku_name": ["nama barang", "nama_barang", "nama produk", "product name",
                 "productname", "nama sku", "nama jns brg", "deskripsi",
                 "description", "item", "nama"],
    "sku_code": ["kode produk", "kode barang", "productcode", "product code",
                 "sap_code", "sap code", "pcode", "kode sku", "item code",
                 "kode"],
    "qty": ["box/qty", "qty jual", "qty_jual", "totalquantity", "total quantity",
            "quantity", "qty karton", "karton", "jumlah", "qty", "pcs"],
    "unit": ["satuan", "satuan jual", "satuan_jual", "uom", "unit", "unit jual",
             "sat", "kemasan", "jenis qty", "jenis_qty", "tipe qty", "qty unit",
             "unit qty"],
    "customer": ["nama customer", "nama_customer", "customername", "nama toko",
                 "customer", "toko", "outlet", "pelanggan"],
    "customer_code": ["kode toko", "customercode", "kode customer", "kode outlet"],
    "salesman_code": ["kode salesman", "salesmancode", "kode sales", "sales code"],
    "salesman_name": ["nama salesman", "salesmanname", "salesman", "sales"],
    "area": ["area", "kota", "wilayah", "city"],
    "kg": ["sum kg", "sum_kg", "total kg", "berat", "weight", "kg"],
    "status": ["status", "order status", "status order"],
}


def read_file(path_or_buffer, header_row=0, skip_rows=0, delimiter=",",
              encoding="utf-8", sheet=0):
    """Read xlsx/xls/csv into a DataFrame. `path_or_buffer` may be a path or bytes."""
    name = getattr(path_or_buffer, "name", str(path_or_buffer)).lower()
    skiprows = list(range(skip_rows)) if skip_rows else None
    if name.endswith(".csv") or name.endswith(".txt"):
        return pd.read_csv(path_or_buffer, header=header_row, skiprows=skiprows,
                           sep=delimiter, encoding=encoding, dtype=str,
                           keep_default_na=False)
    # Excel
    engine = "openpyxl" if name.endswith(".xlsx") else None
    return pd.read_excel(path_or_buffer, header=header_row, skiprows=skiprows,
                         sheet_name=sheet, engine=engine, dtype=str)


def _norm_header(h):
    return re.sub(r"\s+", " ", str(h).strip().lower())


# Headers that look like a unit column but are NOT (avoid false positives such as
# "Unit Price" / "Harga Satuan" being mistaken for the per-row Satuan column).
_UNIT_EXCLUDE = ["price", "harga", "cost", "value", "nilai", "rp", "amount",
                 "total", "jumlah", "qty", "quantity", "disc"]


def _word_match(cand, h):
    """True if `cand` appears in header `h` as a whole word/phrase (not a
    substring of a larger word). Keeps 'unit' from matching 'unit price'."""
    return re.search(r"(?<![a-z])" + re.escape(cand) + r"(?![a-z])", h) is not None


def auto_detect_columns(df):
    """Map each standard field to the best-matching column header in df.

    Returns { field: column_name } for confidently detected fields. The optional
    'unit' (Satuan) field uses stricter, word-boundary matching plus an exclude
    list so a quantity/price column is never mistaken for the unit column.
    """
    headers = {col: _norm_header(col) for col in df.columns}
    detected = {}
    used = set()
    for field, candidates in SYNONYMS.items():
        match = None
        # exact match first (applies to every field)
        for cand in candidates:
            for col, h in headers.items():
                if col in used:
                    continue
                if h == cand:
                    match = col
                    break
            if match:
                break
        # fallback match
        if not match:
            for cand in candidates:
                for col, h in headers.items():
                    if col in used:
                        continue
                    if field == "unit":
                        # strict: whole-word match, skip price/qty-like headers
                        if any(x in h for x in _UNIT_EXCLUDE):
                            continue
                        ok = _word_match(cand, h)
                    else:
                        ok = (cand in h or h in cand)
                    if ok:
                        match = col
                        break
                if match:
                    break
        if match:
            detected[field] = match
            used.add(match)
    return detected
