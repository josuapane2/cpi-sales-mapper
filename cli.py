"""CPI Sales Data Mapper - local command-line interface (no Streamlit).

For local development / batch processing. Examples:

  # list the available distributor templates
  python cli.py list

  # inspect a raw file: detected columns + preview
  python cli.py inspect tests/test_data/cpu_may.csv

  # process a file with a chosen distributor template
  python cli.py process tests/test_data/cpu_may.csv --dist CPU
  python cli.py process raw.xlsx --dist PANJUNAN_BANDUNG --unit pcs --out output

Outputs one 19-column .xlsx per month into the --out folder (default: output/).
"""
from __future__ import annotations

import argparse
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from mapper.loaders import load_master, load_distributors, load_settings
from mapper.matcher import ProductMatcher
from mapper.engine import MappingEngine
from mapper.validator import validate
from utils.file_parser import read_file, auto_detect_columns
from utils.date_parser import make_normalizer
from utils.exporter import build_filename, split_by_month, save_xlsx


def _paths():
    settings = load_settings(os.path.join(BASE, "config", "settings.yaml"))
    master_path = os.path.join(BASE, settings["paths"]["master_product"])
    dist_path = os.path.join(BASE, settings["paths"]["distributors"])
    return settings, master_path, dist_path


def _load():
    _, master_path, dist_path = _paths()
    if not os.path.exists(master_path):
        sys.exit(f"ERROR: master not found at {master_path}\n"
                 f"Run: python scripts/import_master.py")
    return load_master(master_path), load_distributors(dist_path)


def cmd_list(args):
    _, dists = _load()
    print(f"{len(dists)} distributor templates:\n")
    for key in dists:
        d = dists[key]["distributor"]
        unit = dists[key].get("columns", {}).get("qty_unit", "pcs")
        print(f"  {key:22s} {d.get('name',''):32s} "
              f"[{d.get('type','')}, {d.get('area','')}, unit={unit}]")


def cmd_inspect(args):
    df = read_file(args.file, header_row=args.header, skip_rows=args.skip).fillna("")
    detected = auto_detect_columns(df)
    print(f"File: {args.file}")
    print(f"Rows: {len(df)}   Columns: {list(df.columns)}\n")
    print("Auto-detected mapping:")
    for k, v in detected.items():
        print(f"  {k:14s} <- {v!r}")
    print("\nPreview (first 8 rows):")
    print(df.head(8).to_string(index=False))


def cmd_process(args):
    master, dists = _load()
    if args.dist not in dists:
        sys.exit(f"ERROR: unknown distributor '{args.dist}'. Run: python cli.py list")
    engine = MappingEngine(ProductMatcher(master))
    template = dists[args.dist]

    df = read_file(args.file, header_row=args.header, skip_rows=args.skip).fillna("")
    overrides = auto_detect_columns(df)
    if args.unit:
        overrides["qty_unit"] = args.unit
    normalizer = make_normalizer(dayfirst=not args.month_first)
    out_df, report = engine.process(df, template, overrides=overrides,
                                     date_normalizer=normalizer)

    print(f"\n=== {template['distributor'].get('name', args.dist)} ===")
    print(f"Input rows         : {len(df)}")
    print(f"Output rows        : {report['total_rows']}")
    print(f"Draft skipped      : {report['skipped_draft']}")
    print(f"Unmapped products  : {report['unmapped_count']}")
    print(f"Total KG           : {report['total_kg']:,.2f}")
    if report.get("by_brand"):
        print("KG by brand        : " +
              ", ".join(f"{b}={v:,.1f}" for b, v in report["by_brand"].items()))
    if report.get("unmapped_products"):
        print("\nUNMAPPED (assign manually / fix name):")
        for name, count in report["unmapped_products"]:
            print(f"  ({count}x) {name}")

    v = validate(out_df.to_dict("records"))
    s = v["summary"]
    print("\nValidation:")
    print(f"  RTG violations   : {s['rtg_violations']}" +
          ("  <-- MUST be 0!" if s["rtg_violations"] else "  OK"))
    print(f"  KG inconsistent  : {s['kg_inconsistent']}")
    print(f"  Duplicates       : {s['duplicates']}")

    out_dir = args.out or "output"
    os.makedirs(os.path.join(BASE, out_dir), exist_ok=True)
    alias = template["distributor"].get("alias", args.dist)
    written = []
    if args.no_split:
        fname = build_filename(alias, "All")
        save_xlsx(out_df, os.path.join(BASE, out_dir, fname))
        written.append(f"{fname} ({len(out_df)} rows)")
    else:
        for month, sub in split_by_month(out_df):
            fname = build_filename(alias, month)
            save_xlsx(sub, os.path.join(BASE, out_dir, fname))
            written.append(f"{fname} ({len(sub)} rows)")
    print("\nWrote:")
    for w in written:
        print(f"  {out_dir}/{w}")
    if args.preview:
        print("\nPreview:")
        print(out_df.head(args.preview).to_string(index=False))


def build_parser():
    p = argparse.ArgumentParser(prog="cli.py", description="CPI Sales Data Mapper (local CLI)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list distributor templates")
    pl.set_defaults(func=cmd_list)

    pi = sub.add_parser("inspect", help="inspect a raw file's columns")
    pi.add_argument("file")
    pi.add_argument("--header", type=int, default=0, help="header row index (0-based)")
    pi.add_argument("--skip", type=int, default=0, help="rows to skip before header")
    pi.set_defaults(func=cmd_inspect)

    pp = sub.add_parser("process", help="process a raw file into the 19-column format")
    pp.add_argument("file")
    pp.add_argument("--dist", required=True, help="distributor key (see: cli.py list)")
    pp.add_argument("--unit", choices=["pcs", "karton", "innerbox"], help="override quantity unit")
    pp.add_argument("--out", default="output", help="output folder (default: output)")
    pp.add_argument("--header", type=int, default=0)
    pp.add_argument("--skip", type=int, default=0)
    pp.add_argument("--no-split", action="store_true", help="one combined file instead of per-month")
    pp.add_argument("--month-first", action="store_true", help="dates are MM/DD/YYYY")
    pp.add_argument("--preview", type=int, default=0, help="print N preview rows")
    pp.set_defaults(func=cmd_process)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
