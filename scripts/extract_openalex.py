"""Stream a bounded OpenAlex extraction to local UTF-8 JSONL."""

import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import sys

import requests

from src.extract.openalex_client import OpenAlexClient


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
    parser.add_argument("--output-dir", type=Path, default=Path("data/raw/openalex"))
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
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    started = datetime.now(timezone.utc)
    stem = f"{args.keyword}_{args.year}_{started:%Y%m%dT%H%M%S%fZ}"
    data_path = args.output_dir / f"{stem}.jsonl"
    metadata_path = args.output_dir / f"{stem}.metadata.json"
    data_pending = data_path.with_suffix(".jsonl.inprogress")
    metadata_pending = metadata_path.with_suffix(".json.inprogress")
    count = 0
    client = OpenAlexClient()
    print(f"Extracting {args.keyword}, year={args.year}, "
          f"max_records={args.max_records}, per_page={args.per_page}")
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with data_pending.open("x", encoding="utf-8") as output:
            for work in client.iter_works(
                keyword_slug=args.keyword, publication_year=args.year,
                per_page=args.per_page, max_records=args.max_records,
            ):
                output.write(json.dumps(work, ensure_ascii=False) + "\n")
                count += 1
                if count % 100 == 0:
                    print(f"Written {count} records")

        matches = client.source_match_count
        matches = matches if type(matches) is int and matches >= 0 else None
        metadata = {
            "source": "OpenAlex", "entity": "works",
            "keyword": args.keyword, "publication_year": args.year,
            "extracted_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "requested_max_records": args.max_records,
            "actual_record_count": count, "per_page": args.per_page,
            "authentication_used": client.authentication_used,
            "source_match_count": matches,
            "records_extracted": count,
            "max_records_requested": args.max_records,
            "is_complete_extraction": matches is not None and count >= matches,
        }
        with metadata_pending.open("x", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
            output.write("\n")
        data_pending.rename(data_path)
        # Publish provenance last: the final sidecar signals a completed run.
        metadata_pending.rename(metadata_path)
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as error:
        # Exception text can contain credential-bearing URLs; keep it private.
        if isinstance(error, requests.HTTPError) and error.response is not None:
            reason = f"OpenAlex HTTP {error.response.status_code}; check API access/limits"
        elif isinstance(error, (requests.Timeout, requests.ConnectionError)):
            reason = "network connection or timeout failure after retries"
        elif isinstance(error, OSError) and not isinstance(error, requests.RequestException):
            reason = "output file error; check disk space and permissions"
        else:
            reason = "request or response format error"
        print(
            f"Extraction failed after {count} records: {reason}. Files without a final "
            "metadata sidecar are incomplete.", file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Extraction interrupted; in-progress files are incomplete.", file=sys.stderr)
        return 130
    finally:
        client.close()
    print(f"Extraction complete: {count} records\nData: {data_path}\nMetadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
