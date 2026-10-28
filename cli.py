"""Command-line runner (no browser needed).

Examples:
  python cli.py --input data/sample_companies_demo.csv --mode demo
  python cli.py --names "HubSpot | hubspot.com" "Okta" --mode live
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

from leadgen.config import OUTPUT_DIR, load_settings
from leadgen.exporter import results_to_csv, results_to_dataframe, results_to_json
from leadgen.icp import ICP, ICPError
from leadgen.llm import LLMError
from leadgen.pipeline import run_pipeline
from leadgen.validation import ValidationError, limit_companies, parse_company_lines, parse_csv


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="B2B lead qualification (public data only).")
    ap.add_argument("--input", help="CSV with company_name[,website]")
    ap.add_argument("--names", nargs="*", help='Company names, e.g. "Acme | acme.com"')
    ap.add_argument("--mode", choices=["demo", "live"], default="demo")
    ap.add_argument("--extractor", choices=["auto", "llm", "rules"], default="auto")
    ap.add_argument("--icp", help="Path to an ICP JSON file (default: data/icp_default.json)")
    ap.add_argument("--out", default=str(OUTPUT_DIR), help="Output folder")
    args = ap.parse_args(argv)

    settings = load_settings()
    try:
        icp = ICP.load(args.icp) if args.icp else ICP()
        if args.input:
            with open(args.input, "rb") as fh:
                companies, errors = parse_csv(fh.read())
        elif args.names:
            companies, errors = parse_company_lines("\n".join(args.names))
        else:
            ap.error("provide --input or --names")
        companies, warn = limit_companies(companies, settings.max_companies)
        for msg in errors + ([warn] if warn else []):
            print("WARNING:", msg, file=sys.stderr)
        if not companies:
            print("No valid companies to process.", file=sys.stderr)
            return 2
        results = run_pipeline(
            companies, icp, settings, mode=args.mode, extractor=args.extractor,
            progress=lambda i, n, name: print(f"[{i}/{n}] {name}") if name != "done" else None)
    except (ICPError, ValidationError, LLMError, OSError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        return 1

    import pathlib
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path, json_path = out / f"results_{stamp}.csv", out / f"results_{stamp}.json"
    csv_path.write_text(results_to_csv(results), encoding="utf-8-sig")
    json_path.write_text(results_to_json(results, icp), encoding="utf-8")
    df = results_to_dataframe(results)[["Company", "Score", "Decision", "Data Coverage %"]]
    print(df.to_string(index=False))
    print(f"\nSaved:\n  {csv_path}\n  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
