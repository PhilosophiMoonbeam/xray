import pytest

from xray.models import (
    dump_error_envelope,
    dump_explore_envelope,
    dump_impact_result,
    dump_symbol_output,
    validate_symbol_input,
)


def test_symbol_input_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="Symbol input field 'name'"):
        validate_symbol_input({"path": "src/sample.py"})


def test_symbol_output_dump_preserves_sparse_shape_and_extras():
    payload = dump_symbol_output(
        {
            "name": "target_function",
            "path": "src/sample.py",
            "type": "function",
            "start_line": 1,
            "end_line": None,
            "abs_path": None,
            "custom": "kept",
        }
    )

    assert payload == {
        "name": "target_function",
        "path": "src/sample.py",
        "type": "function",
        "start_line": 1,
        "custom": "kept",
    }


def test_explore_envelope_dump_validates_nested_entries():
    payload = dump_explore_envelope(
        {
            "schema_version": "xray.cli.v1",
            "ok": True,
            "command": "explore",
            "invoked_as": "map",
            "root_path": "/repo",
            "tree_text": "/repo\nsrc",
            "warnings": [],
            "entries": [
                {"path": ".", "abs_path": "/repo", "name": "repo", "kind": "directory", "depth": 0},
                {
                    "path": "src/sample.py",
                    "abs_path": "/repo/src/sample.py",
                    "name": "sample.py",
                    "kind": "file",
                    "depth": 2,
                    "language": "python",
                    "symbols": [
                        {
                            "name": "target_function",
                            "type": "function",
                            "signature": "def target_function(value):",
                            "doc": "",
                        }
                    ],
                },
            ],
            "options": {
                "max_depth": None,
                "include_symbols": True,
                "focus_dirs": [],
                "max_symbols_per_file": 5,
            },
        }
    )

    assert payload["invoked_as"] == "map"
    assert payload["options"]["max_depth"] is None
    assert payload["entries"][1]["symbols"][0]["signature"] == "def target_function(value):"


def test_impact_result_dump_preserves_reference_shape():
    payload = dump_impact_result(
        {
            "references": [{"file": "/repo/src/sample.py", "line": 5, "text": "target_function(41)"}],
            "total_count": 1,
            "strategy": "text",
            "note": "Found 1 references using text search.",
        }
    )

    assert payload["references"] == [{"file": "/repo/src/sample.py", "line": 5, "text": "target_function(41)"}]


def test_error_envelope_dump_omits_absent_command():
    payload = dump_error_envelope({"schema_version": "xray.cli.v1", "error": "invalid args"})

    assert payload == {
        "schema_version": "xray.cli.v1",
        "ok": False,
        "command": None,
        "error": "invalid args",
        "warnings": [],
    }
