"""Reusable bounded JSONL extraction and atomic provenance publication."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import requests
from src.config import RAW_DIRECTORY, PathLike, resolve_path
from src.extract.openalex_client import OpenAlexClient


class ExtractionError(ValueError):
    """Safe public diagnostic; original request exception remains chained."""


@dataclass(frozen=True)
class ExtractionResult:
    data_path: Path
    metadata_path: Path
    records: int


def extract_works(*, keyword: str = 'machine-learning', year: int = 2025,
                  max_records: int = 250, per_page: int = 100,
                  output_dir: PathLike = RAW_DIRECTORY,
                  client: OpenAlexClient | None = None) -> ExtractionResult:
    """Publish a bounded extraction; always close the supplied/created client."""
    output_dir = resolve_path(output_dir)
    started = datetime.now(timezone.utc)
    stem = f"{keyword}_{year}_{started:%Y%m%dT%H%M%S%fZ}"
    data_path = output_dir / f"{stem}.jsonl"
    metadata_path = output_dir / f"{stem}.metadata.json"
    data_pending = data_path.with_suffix(".jsonl.inprogress")
    metadata_pending = metadata_path.with_suffix(".json.inprogress")
    count = 0
    client = client or OpenAlexClient()
    print(f"Extracting {keyword}, year={year}, "
          f"max_records={max_records}, per_page={per_page}")
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with data_pending.open("x", encoding="utf-8") as output:
            for work in client.iter_works(
                keyword_slug=keyword, publication_year=year,
                per_page=per_page, max_records=max_records,
            ):
                output.write(json.dumps(work, ensure_ascii=False) + "\n")
                count += 1
                if count % 100 == 0:
                    print(f"Written {count} records")

        matches = client.source_match_count
        matches = matches if type(matches) is int and matches >= 0 else None
        metadata = {
            "source": "OpenAlex", "entity": "works",
            "keyword": keyword, "publication_year": year,
            "extracted_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "requested_max_records": max_records,
            "actual_record_count": count, "per_page": per_page,
            "authentication_used": client.authentication_used,
            "source_match_count": matches,
            "records_extracted": count,
            "max_records_requested": max_records,
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
        raise ExtractionError(
            f"Extraction failed after {count} records: {reason}. Files without a final "
            "metadata sidecar are incomplete."
        ) from error
    finally:
        client.close()
    return ExtractionResult(data_path, metadata_path, count)
