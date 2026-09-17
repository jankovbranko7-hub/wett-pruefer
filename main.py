#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
from dotenv import load_dotenv
from analyze import analyze
from footystats import FootyStats, FootyStatsError
load_dotenv(Path(__file__).resolve().parent / ".env")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spiel", nargs="+")
    args = parser.parse_args()
    key = os.environ.get("FOOTYSTATS_API_KEY", "").strip()
    try:
        print(analyze(FootyStats(key), " ".join(args.spiel)))
    except (FootyStatsError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
