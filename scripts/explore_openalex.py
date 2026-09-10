"""Run from the repository root: python -m scripts.explore_openalex."""

import sys

import requests

from src.extract.openalex_client import OpenAlexClient


PUBLICATION_YEAR = 2025


def print_summary(payload: dict) -> None:
    """Display useful fields while allowing missing or null optional values."""
    meta = payload.get("meta") or {}
    print(f"Total matching works: {meta.get('count', 'Unknown')}")
    works = payload.get("results") or []
    if not works:
        print("No works returned.")

    for index, work in enumerate(works, start=1):
        topic = work.get("primary_topic") or {}
        year = work.get("publication_year")
        citations = work.get("cited_by_count")
        print(f"\n{index}. {work.get('title') or 'Untitled'}")
        print(f"   Year: {year if year is not None else 'Unknown'}")
        print(f"   Citations: {citations if citations is not None else 'Unknown'}")
        print(f"   Type: {work.get('type') or 'Unknown'}")
        print(f"   Primary topic: {topic.get('display_name') or 'Unknown'}")


def main() -> int:
    client = OpenAlexClient()
    try:
        payload = client.fetch_works(
            keyword_slug="machine-learning",
            publication_year=PUBLICATION_YEAR,
            per_page=10,
        )
    except requests.exceptions.JSONDecodeError:
        print("OpenAlex returned invalid JSON. Try again later.", file=sys.stderr)
        return 1
    except requests.RequestException:
        # Do not print the exception or URL: it may include the API key.
        print(
            "OpenAlex request failed. Check your connection and API key, "
            "or try again later.",
            file=sys.stderr,
        )
        return 1
    finally:
        client.close()

    print(f"Machine Learning works published in {PUBLICATION_YEAR}")
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
