"""Export the 19-column unified output to XLSX (one file per distributor/month)."""
from __future__ import annotations

import io
import re

import pandas as pd

from mapper.engine import OUTPUT_COLUMNS


def _safe(s):
    return re.sub(r"[^A-Za-z0-9_-]+", "", str(s)) or "Dist"


def build_filename(alias, month_label):
    """Return e.g. KBB_May_Mapped.xlsx"""
    return f"{_safe(alias)}_{_safe(month_label)}_Mapped.xlsx"


def to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    """Serialize a single dataframe to xlsx bytes with the 19 columns enforced."""
    df = df.reindex(columns=OUTPUT_COLUMNS)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Mapped")
        ws = writer.sheets["Mapped"]
        for i, col in enumerate(OUTPUT_COLUMNS, start=1):
            width = max(12, min(40, len(col) + 4))
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    buf.seek(0)
    return buf.getvalue()


def save_xlsx(df: pd.DataFrame, path: str):
    with open(path, "wb") as fh:
        fh.write(to_xlsx_bytes(df))
    return path


def split_by_month(df: pd.DataFrame, date_col="Tgl Faktur"):
    """Yield (month_label 'YYYY-MM', sub_df) for each month present."""
    if df.empty:
        yield ("all", df)
        return
    months = df[date_col].astype(str).str.slice(0, 7)
    for m in sorted(months.dropna().unique()):
        if not m or m == "nan":
            continue
        yield (m, df[months == m])


def active_outlets_by_month(df: pd.DataFrame,
                            date_col="Tgl Faktur",
                            code_col="Kode Toko",
                            name_col="Nama Toko"):
    """Count distinct active outlets per month.

    An outlet is identified by its customer code ('Kode Toko') when present,
    falling back to the customer name ('Nama Toko') where the code is blank.
    Months are derived from 'Tgl Faktur' (YYYY-MM).

    Returns a DataFrame with columns [Month, Active Outlets], sorted by month,
    plus a final 'TOTAL (distinct)' row counting unique outlets across all months.
    """
    cols = ["Month", "Active Outlets"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    tmp = df.copy()
    tmp["Month"] = tmp[date_col].astype(str).str.slice(0, 7)
    code = (tmp[code_col].astype(str).str.strip()
            if code_col in tmp.columns else pd.Series([""] * len(tmp), index=tmp.index))
    name = (tmp[name_col].astype(str).str.strip()
            if name_col in tmp.columns else pd.Series([""] * len(tmp), index=tmp.index))
    # prefer the code; use the name only where the code is blank/'nan'
    code = code.where(~code.isin(["", "nan", "None"]), "")
    tmp["_outlet"] = code.where(code != "", name)
    tmp = tmp[(tmp["_outlet"].isin(["", "nan", "None"]) == False)
              & (tmp["Month"].str.len() == 7)]
    if tmp.empty:
        return pd.DataFrame(columns=cols)
    g = (tmp.groupby("Month")["_outlet"].nunique()
         .reset_index(name="Active Outlets")
         .sort_values("Month")
         .reset_index(drop=True))
    total = pd.DataFrame([{"Month": "TOTAL (distinct)",
                           "Active Outlets": int(tmp["_outlet"].nunique())}])
    return pd.concat([g, total], ignore_index=True)
