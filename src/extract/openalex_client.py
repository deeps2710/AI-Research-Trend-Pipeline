"""A small OpenAlex Works client for Stage 1 exploration."""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_URL = "https://api.openalex.org"
WORK_FIELDS = (
    "id", "doi", "title", "publication_year", "publication_date",
    "cited_by_count", "primary_topic", "topics", "keywords", "type",
    "authorships", "primary_location", "open_access",
)


class OpenAlexClient:
    """Fetch one page of Works using an optional environment API key."""

    def __init__(self):
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        self._api_key = os.getenv("OPENALEX_API_KEY", "").strip()
        # The example value is a placeholder, never a usable credential.
        if self._api_key == "your_openalex_api_key_here":
            self._api_key = ""
        self.session = requests.Session()

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
        if type(per_page) is not int or not 1 <= per_page <= 100:
            raise ValueError("per_page must be an integer between 1 and 100")

        filters = [f"keywords.id:{keyword_slug}"]
        if publication_year is not None:
            filters.append(f"publication_year:{publication_year}")

        params = {
            "filter": ",".join(filters),
            "per_page": per_page,
            "select": ",".join(WORK_FIELDS),
        }
        if self._api_key:
            params["api_key"] = self._api_key

        response = self.session.get(
            f"{BASE_URL}/works", params=params, timeout=30
        )
        response.raise_for_status()
        return response.json()

    def close(self):
        """Release the session's network connections."""
        self.session.close()
