#!/usr/bin/env python3
"""KPortWatch — Export history data to CSV or JSON.

Usage:
    kportwatch-export                    # today's data as JSON
    kportwatch-export --date 2024-06-01  # specific date
    kportwatch-export --format csv       # CSV output
    kportwatch-export --output data.csv  # custom output path
    kportwatch-export --type alert       # only alerts
    kportwatch-export --type summary     # only summaries
    kportwatch-export --last 100         # last 100 entries
    kportwatch-export --list-dates       # show available dates
"""
from __future__ import annotations

import argparse
import sys

from backend.history import (
    export_history_csv,
    export_history_json,
    list_available_dates,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export KPortWatch history data",
    )
    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="Date to export (YYYY-MM-DD). Default: today",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--type", "-t",
        choices=["summary", "alert"],
        default=None,
        help="Filter by event type",
    )
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        help="Only export the last N entries",
    )
    parser.add_argument(
        "--list-dates",
        action="store_true",
        help="List all dates with history data",
    )
    args = parser.parse_args()

    if args.list_dates:
        dates = list_available_dates()
        if not dates:
            print("No history data found.")
        else:
            for d in dates:
                print(d)
        return

    if args.output:
        outpath = args.output
    else:
        ext = "csv" if args.format == "csv" else "json"
        date = args.date or "today"
        outpath = f"kportwatch-export-{date}.{ext}"

    if args.format == "csv":
        count = export_history_csv(outpath, date=args.date, event_type=args.type)
    else:
        count = export_history_json(outpath, date=args.date, event_type=args.type)

    if count == 0:
        print(f"No entries found for {args.date or 'today'}.", file=sys.stderr)
        sys.exit(1)

    print(f"Exported {count} entries to {outpath}")


if __name__ == "__main__":
    main()
