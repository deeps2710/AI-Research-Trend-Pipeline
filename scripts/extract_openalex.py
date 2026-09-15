"""Stream a bounded OpenAlex extraction to local UTF-8 JSONL."""

import argparse
from pathlib import Path
import re
import sys


from src.extract.openalex_client import OpenAlexClient
from src.extract.extraction import extract_works, ExtractionError
from src.config import RAW_DIRECTORY
from src.logging_config import configure_logging


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", default="machine-learning")
    parser.add_argument("--year", type=positive_int, default=2025)
    parser.add_argument("--max-records", type=positive_int, default=250)
    parser.add_argument("--per-page", type=positive_int, default=100)
    parser.add_argument("--output-dir", type=Path, default=RAW_DIRECTORY)
    args = parser.parse_args(argv)
    if args.per_page > 100:
        parser.error("--per-page must be between 1 and 100")
    if args.year > 9999:
        parser.error("--year must be between 1 and 9999")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.keyword):
        parser.error("--keyword must be a lowercase hyphen-separated slug")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        configure_logging()
        result = extract_works(**vars(args), client=OpenAlexClient())
    except ExtractionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Extraction interrupted; in-progress files are incomplete.", file=sys.stderr)
        return 130
    print(f"Extraction complete: {result.records} records\nData: {result.data_path}\nMetadata: {result.metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
