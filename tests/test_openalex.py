"""Offline checks for request construction and safe exploration output."""

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch

import requests

from scripts.explore_openalex import main, print_summary
from src.extract.openalex_client import OpenAlexClient, WORK_FIELDS


class OpenAlexTests(unittest.TestCase):
    def setUp(self):
        with patch("src.extract.openalex_client.load_dotenv"), patch.dict(
            "os.environ", {"OPENALEX_API_KEY": ""}
        ):
            self.client = OpenAlexClient()
        self.addCleanup(self.client.close)

    def test_request_filters_fields_and_status_before_json(self):
        response = Mock()
        response.json.return_value = {"meta": {"count": 1}, "results": []}
        with patch.object(self.client.session, "get", return_value=response) as get:
            result = self.client.fetch_works(publication_year=2025)
        get.assert_called_once_with(
            "https://api.openalex.org/works",
            params={
                "filter": "keywords.id:machine-learning,publication_year:2025",
                "per_page": 10,
                "select": ",".join(WORK_FIELDS),
            },
            timeout=30,
        )
        self.assertEqual(result, response.json.return_value)
        self.assertEqual([call[0] for call in response.method_calls],
                         ["raise_for_status", "json"])

    def test_optional_key_and_keyword_without_year(self):
        self.client._api_key = "unit-test-placeholder"
        with patch.object(self.client.session, "get") as get:
            self.client.fetch_works(keyword_slug="deep-learning", per_page=100)
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["api_key"], "unit-test-placeholder")
        self.assertEqual(params["filter"], "keywords.id:deep-learning")

    def test_invalid_page_sizes_never_make_request(self):
        with patch.object(self.client.session, "get") as get:
            for value in (0, 101, -1, True, 1.5, "10", None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.client.fetch_works(per_page=value)
        get.assert_not_called()

    def test_http_failure_does_not_parse_json(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError()
        with patch.object(self.client.session, "get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                self.client.fetch_works(per_page=1)
        response.json.assert_not_called()

    def test_missing_optional_values_and_zero_citations(self):
        output = io.StringIO()
        with redirect_stdout(output):
            print_summary({"meta": None, "results": [
                {"title": None, "primary_topic": None, "cited_by_count": 0}, {}
            ]})
        self.assertIn("Primary topic: Unknown", output.getvalue())
        self.assertIn("Citations: 0", output.getvalue())

    def test_script_errors_do_not_print_request_url(self):
        with patch("scripts.explore_openalex.OpenAlexClient") as client_class:
            client = client_class.return_value
            client.fetch_works.side_effect = requests.HTTPError(
                "https://api.openalex.org/works?api_key=unit-test-placeholder"
            )
            output = io.StringIO()
            with redirect_stderr(output):
                self.assertEqual(main(), 1)
            self.assertNotIn("unit-test-placeholder", output.getvalue())
            client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
