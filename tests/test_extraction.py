"""Offline tests for retries, streaming limits, and extraction files."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, call, patch

import requests

from scripts.extract_openalex import main, parse_args
from src.extract.openalex_client import OpenAlexClient, RETRY_STATUSES


def response(status=200, works=None, cursor=None):
    result = Mock(status_code=status, headers={})
    result.json.return_value = {
        "results": works or [], "meta": {"next_cursor": cursor}
    }
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError("private URL")
    return result


class ClientTests(unittest.TestCase):
    def setUp(self):
        with patch("src.extract.openalex_client.load_dotenv"), patch.dict(
            "os.environ", {"OPENALEX_API_KEY": ""}
        ):
            self.client = OpenAlexClient()
        self.addCleanup(self.client.close)

    @patch("src.extract.openalex_client.time.sleep")
    def test_transient_statuses_retry(self, sleep):
        for status in RETRY_STATUSES:
            with self.subTest(status=status), patch.object(
                self.client.session, "get", side_effect=[response(status), response()]
            ) as get:
                self.client.fetch_works()
                self.assertEqual(get.call_count, 2)
        self.assertEqual(sleep.call_args_list, [call(1)] * len(RETRY_STATUSES))

    @patch("src.extract.openalex_client.time.sleep")
    def test_network_retry_exhaustion_and_backoff(self, sleep):
        for error in (requests.Timeout, requests.ConnectionError):
            sleep.reset_mock()
            with self.subTest(error=error), patch.object(
                self.client.session, "get", side_effect=error("private URL")
            ) as get, self.assertLogs("src.extract.openalex_client") as logs:
                with self.assertRaises(error):
                    self.client.fetch_works()
                self.assertEqual(get.call_count, 4)
                self.assertEqual(sleep.call_args_list, [call(1), call(2), call(4)])
                self.assertNotIn("private URL", " ".join(logs.output))

    @patch("src.extract.openalex_client.time.sleep")
    def test_http_exhaustion_and_nonretryable_errors(self, sleep):
        for status, attempts in ((503, 4), (400, 1), (401, 1), (404, 1)):
            with self.subTest(status=status), patch.object(
                self.client.session, "get", return_value=response(status)
            ) as get:
                with self.assertRaises(requests.HTTPError):
                    self.client.fetch_works()
                self.assertEqual(get.call_count, attempts)
        self.assertEqual(sleep.call_args_list, [call(1), call(2), call(4)])

    def test_rate_limits_and_auth_boolean(self):
        reply = response()
        reply.headers = {"X-RateLimit-Remaining": "99", "Other": "unused"}
        with patch.object(self.client.session, "get", return_value=reply):
            self.client.fetch_works()
        self.assertEqual(self.client.rate_limits, {"X-RateLimit-Remaining": "99"})
        self.assertIs(self.client.authentication_used, False)

    def test_cursor_stream_is_lazy_and_truncates_final_page(self):
        pages = [response(works=[{"id": "1"}, {"id": "2"}], cursor="next"),
                 response(works=[{"id": "3"}, {"id": "4"}], cursor="unused")]
        with patch.object(self.client.session, "get", side_effect=pages) as get:
            works = self.client.iter_works(per_page=2, max_records=3)
            get.assert_not_called()
            self.assertEqual(list(works), [{"id": "1"}, {"id": "2"}, {"id": "3"}])
        self.assertEqual([c.kwargs["params"]["cursor"] for c in get.call_args_list],
                         ["*", "next"])
        self.assertEqual([c.kwargs["params"]["per_page"] for c in get.call_args_list],
                         [2, 1])

    def test_empty_and_null_cursor_stop(self):
        for page in (response(cursor="unused"), response(works=[{"id": "1"}])):
            with patch.object(self.client.session, "get", return_value=page) as get:
                list(self.client.iter_works())
                get.assert_called_once()

    def test_cursor_can_cross_basic_paging_limit(self):
        page_number = 0

        def next_page(*args, **kwargs):
            nonlocal page_number
            page_number += 1
            return response(works=[{"id": page_number}] * 100,
                            cursor=str(page_number))

        with patch.object(self.client.session, "get", side_effect=next_page) as get:
            self.assertEqual(sum(1 for _ in self.client.iter_works(max_records=10001)),
                             10001)
            self.assertEqual(get.call_count, 101)

    def test_invalid_bounds_make_no_request(self):
        with patch.object(self.client.session, "get") as get:
            for value in (0, -1, True, 1.5, "5"):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    list(self.client.iter_works(max_records=value))
            for value in (0, 101, True):
                with self.assertRaises(ValueError):
                    list(self.client.iter_works(per_page=value))
            get.assert_not_called()

    def test_invalid_json_is_not_retried(self):
        reply = response()
        reply.json.side_effect = requests.exceptions.JSONDecodeError("bad", "", 0)
        with patch.object(self.client.session, "get", return_value=reply) as get:
            with self.assertRaises(requests.exceptions.JSONDecodeError):
                self.client.fetch_works()
            get.assert_called_once()

    def test_malformed_response_and_repeated_cursor_fail(self):
        for payload in ({}, {"results": "bad", "meta": {"next_cursor": None}},
                        {"results": [{}], "meta": {"next_cursor": "*"}}):
            with patch.object(self.client, "_request", return_value=payload):
                with self.assertRaises((ValueError, KeyError)):
                    list(self.client.iter_works())


class ScriptTests(unittest.TestCase):
    def test_argument_validation(self):
        for args in (["--max-records", "0"], ["--per-page", "101"],
                     ["--year", "-1"], ["--keyword", "../escape"],
                     ["--max-records", "abc"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    parse_args(args)
                self.assertEqual(raised.exception.code, 2)

    @patch("scripts.extract_openalex.OpenAlexClient")
    def test_jsonl_and_metadata(self, client_class):
        client = client_class.return_value
        client.authentication_used = False
        works = [{"id": "1", "title": "研究"}, {"id": "2", "primary_topic": None}]
        client.iter_works.return_value = iter(works)
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--output-dir", directory, "--max-records", "2"]), 0)
            paths = list(Path(directory).iterdir())
            self.assertEqual(len(paths), 2)
            data = next(Path(directory).glob("*.jsonl"))
            self.assertEqual([json.loads(line) for line in data.read_text(
                encoding="utf-8").splitlines()], works)
            metadata = json.loads(next(Path(directory).glob("*.metadata.json"))
                                  .read_text(encoding="utf-8"))
            self.assertEqual(metadata["actual_record_count"], 2)
            self.assertEqual(metadata["requested_max_records"], 2)
            self.assertIs(metadata["authentication_used"], False)
            self.assertEqual(metadata["source"], "OpenAlex")
            self.assertNotIn("api_key", json.dumps(metadata))
        client.close.assert_called_once()

    @patch("scripts.extract_openalex.OpenAlexClient")
    def test_failure_leaves_only_inprogress_and_no_secret_output(self, client_class):
        def interrupted():
            yield {"id": "1"}
            raise requests.ConnectionError("api_key=unit-test-placeholder")

        client_class.return_value.iter_works.return_value = interrupted()
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()), \
                redirect_stderr(errors):
            self.assertEqual(main(["--output-dir", directory]), 1)
            paths = list(Path(directory).iterdir())
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].name.endswith(".jsonl.inprogress"))
            self.assertNotIn("unit-test-placeholder", errors.getvalue())
        client_class.return_value.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
