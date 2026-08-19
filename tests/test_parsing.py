"""Reading what the model actually returned."""

import pytest

from screencast.parsing import extract_json_object, strip_code_fences


def test_strip_code_fences_removes_the_markers_only():
    raw = '```json\n{"a": 1}\n```'
    assert strip_code_fences(raw).strip() == '{"a": 1}'


def test_extract_json_object_ignores_preamble_and_trailing_prose():
    raw = 'Here is the edit:\n{"timeline": [{"start": 0}]}\nHope this helps!'
    assert extract_json_object(raw) == '{"timeline": [{"start": 0}]}'


def test_extract_json_object_handles_nesting():
    raw = '{"metadata": {"chapters": [{"at": 0}]}, "timeline": []}'
    assert extract_json_object(raw) == raw


def test_extract_json_object_rejects_output_with_no_object():
    with pytest.raises(ValueError, match="no JSON object"):
        extract_json_object("I cannot help with that.")


def test_extract_json_object_rejects_a_truncated_answer():
    # a response cut off mid-generation must fail loudly, not silently half-parse
    with pytest.raises(ValueError, match="unbalanced"):
        extract_json_object('{"timeline": [{"start": 0}')
