"""OpenAlex Works retrieval with bounded retries and cursor pagination."""

import logging
import os
import re
import time
from collections.abc import Iterator
from src.config import PROJECT_ROOT

import requests
from dotenv import load_dotenv


BASE_URL = "https://api.openalex.org"
LOGGER = logging.getLogger(__name__)
RETRY_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_HEADERS = (
    "X-RateLimit-Limit", "X-RateLimit-Remaining",
    "X-RateLimit-Credits-Used", "X-RateLimit-Reset",
)
WORK_FIELDS = (
    "id", "doi", "title", "publication_year", "publication_date",
    "cited_by_count", "primary_topic", "topics", "keywords", "type",
    "authorships", "primary_location", "open_access",
)


class OpenAlexClient:
    """Fetch Works using an optional key; max_retries excludes the first attempt."""

    def __init__(self, max_retries: int = 3):
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        load_dotenv(PROJECT_ROOT / ".env")
        self._api_key = os.getenv("OPENALEX_API_KEY", "").strip()
        # The example value is a placeholder, never a usable credential.
        if self._api_key == "your_openalex_api_key_here":
            self._api_key = ""
        self.session = requests.Session()
        self.max_retries = max_retries
        self.rate_limits = {}
        self.source_match_count = None

    @property
    def authentication_used(self) -> bool:
        """Expose authentication state without exposing the credential."""
        return bool(self._api_key)

    def _request(self, params: dict) -> dict:
        """Retry transient failures only; never log exceptions or request URLs."""
        params = dict(params)
        if self._api_key:
            params["api_key"] = self._api_key

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(
                    f"{BASE_URL}/works", params=params, timeout=30
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt == self.max_retries:
                    raise
                reason = "connection failure or timeout"
            else:
                self.rate_limits = {
                    name: response.headers[name]
                    for name in RATE_LIMIT_HEADERS if name in response.headers
                }
                if (response.status_code not in RETRY_STATUSES
                        or attempt == self.max_retries):
                    response.raise_for_status()
                    return response.json()
                reason = f"HTTP {response.status_code}"
                response.close()

            delay = 2 ** attempt
            LOGGER.warning(
                "OpenAlex %s; retry %d/%d in %d seconds",
                reason, attempt + 1, self.max_retries, delay,
            )
            time.sleep(delay)

    @staticmethod
    def _works_params(keyword_slug, publication_year, per_page) -> dict:
        if type(per_page) is not int or not 1 <= per_page <= 100:
            raise ValueError("per_page must be an integer between 1 and 100")
        if not isinstance(keyword_slug, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", keyword_slug
        ):
            raise ValueError("keyword must be a lowercase hyphen-separated slug")
        if publication_year is not None and (
            type(publication_year) is not int or not 1 <= publication_year <= 9999
        ):
            raise ValueError("publication_year must be an integer from 1 to 9999")
        filters = [f"keywords.id:{keyword_slug}"]
        if publication_year is not None:
            filters.append(f"publication_year:{publication_year}")
        return {
            "filter": ",".join(filters),
            "per_page": per_page,
            "select": ",".join(WORK_FIELDS),
        }

    def fetch_works(
        self,
        keyword_slug: str = "machine-learning",
        publication_year: int | None = None,
        per_page: int = 10,
    ) -> dict:
        """Return decoded Works JSON, including metadata and up to 100 works.

        Request exceptions propagate to the caller. Avoid printing them: their
        request URLs may contain the API key.
        """
        return self._request(
            self._works_params(keyword_slug, publication_year, per_page)
        )

    def iter_works(
        self, keyword_slug: str = "machine-learning",
        publication_year: int | None = None, per_page: int = 100,
        max_records: int | None = None,
    ) -> Iterator[dict]:
        """Yield individual raw Works, holding only one API page in memory."""
        params = self._works_params(keyword_slug, publication_year, per_page)
        if max_records is not None and (
            type(max_records) is not int or max_records <= 0
        ):
            raise ValueError("max_records must be a positive integer")
        cursor = "*"
        count = 0
        self.source_match_count = None
        while cursor is not None:
            params["cursor"] = cursor
            if max_records is not None:
                params["per_page"] = min(per_page, max_records - count)
            payload = self._request(params)
            if cursor == "*":
                matches = payload.get("meta", {}).get("count")
                if type(matches) is int and matches >= 0:
                    self.source_match_count = matches
            # Missing structural fields are errors, not successful empty runs.
            works = payload["results"]
            next_cursor = payload["meta"]["next_cursor"]
            if not isinstance(works, list) or (
                next_cursor is not None and not isinstance(next_cursor, str)
            ):
                raise ValueError("Invalid OpenAlex pagination response")
            if not works:
                return
            for work in works:
                if not isinstance(work, dict):
                    raise ValueError("Invalid OpenAlex Work record")
                yield work
                count += 1
                if max_records is not None and count >= max_records:
                    return
            if next_cursor == cursor:
                raise ValueError("OpenAlex returned a repeated cursor")
            cursor = next_cursor

    def close(self):
        """Release the session's network connections."""
        self.session.close()
