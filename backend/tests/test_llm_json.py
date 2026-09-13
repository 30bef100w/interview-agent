from app.services.llm.client import _parse_json


def test_parse_json_ignores_trailing_text():
    raw = '{"summary": "ok", "score": 7}\nnote: extra'
    assert _parse_json(raw)["summary"] == "ok"


def test_parse_json_strips_trailing_commas():
    raw = '{"summary": "ok", "items": [1, 2,],}'
    assert _parse_json(raw)["summary"] == "ok"
    assert _parse_json(raw)["items"] == [1, 2]
