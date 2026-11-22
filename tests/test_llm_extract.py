"""Tests for the model reader, against a fake OpenAI-compatible service."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from firb_tracer.llm_extract import ModelError, read_with_model, to_extraction
from firb_tracer.model import from_dict

TEXT = ("深圳市国资委持有深圳市资源集团有限公司（以下简称“深圳资源”）100%股权。"
        "深圳资源拟收购香港控股有限公司25%股权。深圳资源与李四签有表决权委托协议。")

ANSWER = {
    "entities": [
        {"name": "深圳市国资委", "kind": "government", "country": "CN"},
        {"name": "深圳市资源集团有限公司", "kind": "corporation", "country": "cn"},
        {"name": "香港控股有限公司", "kind": "corporation", "country": None},
    ],
    "holdings": [
        {"holder": "深圳市国资委", "held": "深圳市资源集团有限公司", "shares_pct": 100, "proposed": False,
         "quote": "深圳市国资委持有深圳市资源集团有限公司（以下简称“深圳资源”）100%股权。"},
        {"holder": "深圳市资源集团有限公司", "held": "香港控股有限公司", "shares_pct": "25%", "proposed": True,
         "board_seats": "1/3", "quote": "深圳资源拟收购香港控股有限公司25%股权。"},
    ],
    "buyer": "深圳市资源集团有限公司",
    "target": "澳洲稀土有限公司",
    "unread": ["深圳资源与李四签有表决权委托协议。"],
}


class FakeService(BaseHTTPRequestHandler):
    status = 200
    reply: object = None
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeService.seen.append((self.path, self.headers["Authorization"], body))
        self.send_response(FakeService.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(FakeService.reply).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def service():
    server = HTTPServer(("127.0.0.1", 0), FakeService)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    FakeService.status, FakeService.seen = 200, []
    FakeService.reply = {"choices": [{"message": {"content": json.dumps(ANSWER, ensure_ascii=False)}}]}
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_request_and_conversion(service):
    x = read_with_model(TEXT, service + "/", "sk-test", "some-model")
    path, auth, body = FakeService.seen[0]
    assert path == "/v1/chat/completions" and auth == "Bearer sk-test"
    assert body["model"] == "some-model" and body["response_format"] == {"type": "json_object"}
    assert "JSON" in body["messages"][0]["content"] and body["messages"][1]["content"] == TEXT

    assert {(h.holder, h.held, h.pct, h.proposed) for h in x.holdings} == {
        ("深圳市国资委", "深圳市资源集团有限公司", 100.0, False),
        ("深圳市资源集团有限公司", "香港控股有限公司", 25.0, True)}
    assert x.holdings[1].board_seats == "1/3"
    assert x.countries == {"深圳市国资委": "CN", "深圳市资源集团有限公司": "CN"}
    assert x.buyer == "深圳市资源集团有限公司" and x.target is None
    assert any("not in any holding" in n for n in x.notes)
    assert x.unread == ["深圳资源与李四签有表决权委托协议。"]

    graph = from_dict(x.to_data())
    assert all(e.gov_status.value == "uncertain" for e in graph.entities.values())
    assert graph.entities["深圳市国资委"].kind.value == "government"
    assert graph.holdings[0].source.startswith("Text (model): ")


def test_fenced_json_is_accepted(service):
    FakeService.reply = {"choices": [{"message": {"content": "```json\n" + json.dumps(ANSWER) + "\n```"}}]}
    assert len(read_with_model(TEXT, service, "k", "m").holdings) == 2


@pytest.mark.parametrize("status, message", [(401, "key was rejected"), (404, "check the base URL"),
                                             (429, "rate or quota")])
def test_http_errors_are_explained(service, status, message):
    FakeService.status, FakeService.reply = status, {"error": "nope"}
    with pytest.raises(ModelError, match=message):
        read_with_model(TEXT, service, "k", "m")


def test_non_json_answer(service):
    FakeService.reply = {"choices": [{"message": {"content": "Sorry, I cannot help."}}]}
    with pytest.raises(ModelError, match="not valid JSON"):
        read_with_model(TEXT, service, "k", "m")


def test_unreachable_service():
    with pytest.raises(ModelError, match="could not reach"):
        read_with_model(TEXT, "http://127.0.0.1:9", "k", "m")


@pytest.mark.parametrize("text, url, key, model, message", [
    ("  ", "u", "k", "m", "no text"),
    ("x" * 30_001, "u", "k", "m", "longer than"),
    ("text", "u", "", "m", "all needed"),
])
def test_input_checks(text, url, key, model, message):
    with pytest.raises(ModelError, match=message):
        read_with_model(text, url, key, model)


def test_invented_quotes_and_bad_rows_are_flagged():
    answer = {"holdings": [
        {"holder": "甲公司", "held": "乙公司", "shares_pct": 30, "quote": "甲公司持有乙公司30%股权"},
        {"holder": "甲公司", "held": "丙公司", "shares_pct": 150, "quote": "x"},
        {"holder": "", "held": "丙公司", "shares_pct": 10},
    ]}
    x = to_extraction(answer, "甲公司持有乙公司 20% 股权")
    assert len(x.holdings) == 1
    assert any("quote is not in your text" in n for n in x.notes)
    assert sum("incompletely" in n for n in x.notes) == 2
