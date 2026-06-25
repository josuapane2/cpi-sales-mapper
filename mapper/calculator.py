"""Quantity conversion and weight (KG) calculation.

The master carries three per-unit weights (kg): weight_kg_carton,
weight_kg_innerbox (RTG only), weight_kg_pcs. Sum_KG for a row is the row's raw
quantity multiplied by the weight that matches the row's unit (Satuan):

    carton   -> qty * weight_kg_carton
    innerbox -> qty * weight_kg_innerbox
    pcs      -> qty * weight_kg_pcs

Packaging used for Qty Kecil / Qty Karton conversion:
    1 carton = Carton_pcs pieces ; for RTG, 1 carton = 6 inner boxes = 72 pcs.
"""
from __future__ import annotations

from .units import normalize_unit, CARTON, INNERBOX, PCS

INNERBOX_PCS = 12     # pieces per RTG inner box
INNERBOX_PER_CARTON = 6  # inner boxes per RTG carton


def _f(v):
    try:
        return float(str(v).replace(",", ".")) if str(v).strip() else 0.0
    except (TypeError, ValueError):
        return 0.0


def convert_qty(qty, unit, carton_pcs):
    """Convert a source quantity into (Qty_Kecil [pcs], Qty_Karton [carton]).

      pcs      -> Qty_Kecil = QTY ;       Qty_Karton = QTY / carton_pcs
      carton   -> Qty_Karton = QTY ;      Qty_Kecil  = QTY * carton_pcs
      innerbox -> Qty_Kecil = QTY * 12 ;  Qty_Karton = QTY / 6   (RTG only)
    """
    unit = normalize_unit(unit, default=PCS)
    qty = _f(qty)
    carton_pcs = _f(carton_pcs)

    if unit == PCS:
        qty_kecil = qty
        qty_karton = (qty / carton_pcs) if carton_pcs else 0.0
    elif unit == CARTON:
        qty_karton = qty
        qty_kecil = qty * carton_pcs if carton_pcs else qty
    elif unit == INNERBOX:
        qty_kecil = qty * INNERBOX_PCS
        qty_karton = qty / INNERBOX_PER_CARTON
    else:  # safety net
        qty_kecil = qty
        qty_karton = (qty / carton_pcs) if carton_pcs else 0.0

    return int(round(qty_kecil)), round(float(qty_karton), 4)


def weight_for_unit(qty, unit, rec, is_rtg=False):
    """Return (weight_perpcs, sum_kg) using the per-unit master weights.

    qty  : the RAW quantity in the row's own unit (not converted to pcs).
    unit : the row's Satuan (any synonym; normalized here).
    rec  : the matched master record (or None).
    """
    unit = normalize_unit(unit, default=PCS)
    qty = _f(qty)

    w_pcs = _f(rec.get("weight_kg_pcs")) if rec else 0.0
    w_carton = _f(rec.get("weight_kg_carton")) if rec else 0.0
    w_ib = _f(rec.get("weight_kg_innerbox")) if rec else 0.0
    carton_pcs = _f(rec.get("Carton_pcs")) if rec else 0.0

    # Derive any missing weight from the others so we always have a value.
    if w_carton <= 0 and w_pcs > 0 and carton_pcs > 0:
        w_carton = w_pcs * carton_pcs
    if w_pcs <= 0 and w_carton > 0 and carton_pcs > 0:
        w_pcs = w_carton / carton_pcs
    if w_ib <= 0 and w_carton > 0:
        w_ib = w_carton / INNERBOX_PER_CARTON

    if unit == CARTON:
        unit_weight = w_carton
    elif unit == INNERBOX:
        unit_weight = w_ib if w_ib > 0 else (w_pcs * INNERBOX_PCS)
    else:  # pcs
        unit_weight = w_pcs

    sum_kg = qty * unit_weight
    return round(w_pcs, 6), round(sum_kg, 4)


# ---- legacy helper kept for backward compatibility (qty already in pcs) ----
def calc_weight(qty_kecil, is_rtg, weight_kg_pcs, *_ignored):
    """Weight from a piece count: Sum_KG = qty_kecil * weight_kg_pcs."""
    qk = _f(qty_kecil)
    wpp = _f(weight_kg_pcs)
    return round(wpp, 6), round(qk * wpp, 4)
