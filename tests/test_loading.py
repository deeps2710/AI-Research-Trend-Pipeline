"""Local reader checks and real DuckDB merge tests; no OpenAlex requests."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from scripts.inspect_warehouse import main as inspect_main
from scripts.load_openalex import main as load_main
from src.load.openalex_dlt import InvalidWorkFile, load_file, read_jsonl, resolve_input


class ReaderTests(unittest.TestCase):
    def test_streaming_validation_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "works.jsonl"
            path.write_text('\n{"id":"W1","title":"研究","topics":null}\nnot json\n',
                            encoding="utf-8")
            reader = read_jsonl(path)
            self.assertEqual(next(reader)["title"], "研究")
            with self.assertRaisesRegex(InvalidWorkFile, "line 3: malformed JSON"):
                next(reader)

    def test_invalid_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "works.jsonl"
            for record in ([], {}, {"id": None}, {"id": " "}, {"id": 1}):
                path.write_text(json.dumps(record), encoding="utf-8")
                with self.subTest(record=record), self.assertRaisesRegex(
                    InvalidWorkFile, "line 1"
                ):
                    list(read_jsonl(path))

    def test_newest_completed_input_only(self):
        with tempfile.TemporaryDirectory() as directory:
            older = Path(directory) / "older.jsonl"
            newer = Path(directory) / "newer.jsonl"
            for path in (older, newer):
                path.write_text('{"id":"W1"}\n', encoding="utf-8")
                path.with_suffix(".metadata.json").write_text("{}", encoding="utf-8")
            os.utime(older, (100, 100))
            os.utime(newer, (200, 200))
            (Path(directory) / "unfinished.jsonl").write_text("{}", encoding="utf-8")
            self.assertEqual(resolve_input(raw_directory=directory), newer.resolve())
            with self.assertRaises(InvalidWorkFile):
                resolve_input(newer.with_suffix(".metadata.json"))

    def test_missing_input_and_database(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stderr(io.StringIO()):
            with self.assertRaises(FileNotFoundError):
                resolve_input(raw_directory=directory)
            missing = str(Path(directory) / "absent.duckdb")
            self.assertEqual(inspect_main(["--database", missing]), 1)
            self.assertFalse(Path(missing).exists())


class MergeTests(unittest.TestCase):
    @patch.dict(os.environ, {"RUNTIME__DLTHUB_TELEMETRY": "false"})
    def test_repeated_load_and_nested_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "works.jsonl"
            database = Path(directory) / "warehouse.duckdb"
            rows = [
                {"id": "W1", "title": "研究", "cited_by_count": 1,
                 "topics": [{"id": "T1"}, {"id": "T2"}],
                 "authorships": [{"author": {"id": "A1"},
                                  "institutions": [{"id": "I1"}]}]},
                {"id": "W2", "topics": None},
            ]
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            load_file(path, database)

            def snapshot():
                with duckdb.connect(str(database), read_only=True) as connection:
                    names = [row[0] for row in connection.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='openalex_data' AND table_name LIKE 'works%'"
                    ).fetchall()]
                    return {name: connection.execute(
                        'SELECT count(*) FROM openalex_data."' + name.replace('"', '""') + '"'
                    ).fetchone()[0] for name in names}

            first = snapshot()
            load_file(path, database)
            self.assertEqual(snapshot(), first)
            self.assertEqual(first["works"], 2)
            rows[0]["cited_by_count"] = 9
            rows[0]["topics"] = [{"id": "T3"}]
            rows[0]["authorships"] = []
            path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            load_file(path, database)
            with duckdb.connect(str(database), read_only=True) as connection:
                self.assertEqual(connection.execute(
                    "SELECT cited_by_count FROM openalex_data.works WHERE id='W1'"
                ).fetchone()[0], 9)
                self.assertEqual(connection.execute(
                    "SELECT id FROM openalex_data.works__topics"
                ).fetchall(), [("T3",)])
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM openalex_data.works__authorships__institutions"
                ).fetchone()[0], 0)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(inspect_main(["--database", str(database)]), 0)

    @patch.dict(os.environ, {"RUNTIME__DLTHUB_TELEMETRY": "false"})
    def test_loader_reports_wrapped_reader_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text('{"id":"W1"}\n{"title":"private-value"}', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(errors):
                status = load_main(["--input-file", str(path), "--database",
                                    str(Path(directory) / "bad.duckdb")])
            self.assertEqual(status, 1)
            self.assertIn("line 2: missing or invalid Work id", errors.getvalue())
            self.assertNotIn("private-value", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
