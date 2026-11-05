"""Drive the real Anthropic SDK against a fake HTTP transport.

These tests pin the request we send and how we read replies. They do not prove the live
API accepts the request; only a run with a real key can do that.
"""

import json

import anthropic
import httpx2
import pytest

from arxiv_radar.config import LLMConfig
from arxiv_radar.llm import FALLBACK_BETA, Reviewer

from conftest import make_paper

REVIEW = {
    "score": 8,
    "title_translated": "标题",
    "tldr": "总结。",
    "method": "方法。",
    "findings": "结果。",
    "why_relevant": "相关。",
    "tags": ["RAG"],
}


def message(text=None, stop_reason="end_turn", **extra):
    content = [{"type": "text", "text": text}] if text is not None else []
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        **extra,
    }


def make_reviewer(handler, **llm_options):
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url="https://api.test",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return Reviewer(LLMConfig(**llm_options), "RAG systems", "zh", client=client)


def replying(body, status=200, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(request)
        return httpx2.Response(status, json=body)

    return handler


def test_request_shape():
    requests = []
    reviewer = make_reviewer(replying(message(json.dumps(REVIEW)), requests=requests))

    reviewer.review(make_paper(title="Paper title", abstract="Paper abstract."))

    request = requests[0]
    body = json.loads(request.content)
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert set(body["output_config"]["format"]["schema"]["required"]) == set(REVIEW)
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    assert "RAG systems" in body["system"]
    assert "Simplified Chinese" in body["system"]
    assert "Paper title" in body["messages"][0]["content"]
    assert "Paper abstract." in body["messages"][0]["content"]


@pytest.mark.parametrize(
    "options",
    [{"model": "claude-haiku-5-5"}, {"refusal_fallback": False}],
    ids=["model-without-fallback", "turned-off"],
)
def test_fallbacks_are_left_out_when_not_applicable(options):
    requests = []
    reviewer = make_reviewer(replying(message(json.dumps(REVIEW)), requests=requests), **options)

    reviewer.review(make_paper())

    assert "fallbacks" not in json.loads(requests[0].content)
    assert FALLBACK_BETA not in requests[0].headers.get("anthropic-beta", "")


def test_parses_review():
    review = make_reviewer(replying(message(json.dumps(REVIEW)))).review(make_paper())
    assert review.score == 8
    assert review.tags == ["RAG"]


def test_clamps_out_of_range_score():
    reply = message(json.dumps({**REVIEW, "score": 42}))
    assert make_reviewer(replying(reply)).review(make_paper()).score == 10


def test_refusal_returns_none():
    reply = message(
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )
    assert make_reviewer(replying(reply)).review(make_paper()) is None


def test_truncated_reply_returns_none():
    reply = message('{"score": 8, "title_tr', stop_reason="max_tokens")
    assert make_reviewer(replying(reply)).review(make_paper()) is None


def test_reply_missing_a_field_returns_none():
    incomplete = {key: value for key, value in REVIEW.items() if key != "tldr"}
    assert make_reviewer(replying(message(json.dumps(incomplete)))).review(make_paper()) is None


@pytest.mark.parametrize("status", [429, 500, 529])
def test_transient_api_errors_skip_the_paper(status):
    error = {"type": "error", "error": {"type": "api_error", "message": "nope"}}
    assert make_reviewer(replying(error, status=status)).review(make_paper()) is None


def test_connection_failure_skips_the_paper():
    def handler(request):
        raise httpx2.ConnectError("refused")

    assert make_reviewer(handler).review(make_paper()) is None


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (400, anthropic.BadRequestError),
        (401, anthropic.AuthenticationError),
        (403, anthropic.PermissionDeniedError),
        (404, anthropic.NotFoundError),
    ],
)
def test_configuration_errors_abort_the_run(status, exception):
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "nope"}}
    with pytest.raises(exception):
        make_reviewer(replying(error, status=status)).review(make_paper())


def test_review_all_keeps_successes_and_drops_failures():
    def handler(request):
        abstract = json.loads(request.content)["messages"][0]["content"]
        if "bad" in abstract:
            return httpx2.Response(200, json=message(stop_reason="refusal"))
        return httpx2.Response(200, json=message(json.dumps(REVIEW)))

    papers = [
        make_paper("good1", abstract="fine"),
        make_paper("bad", abstract="bad"),
        make_paper("good2", abstract="fine"),
    ]
    assert set(make_reviewer(handler).review_all(papers)) == {"good1", "good2"}


def test_review_all_propagates_configuration_errors():
    error = {"type": "error", "error": {"type": "authentication_error", "message": "nope"}}
    with pytest.raises(anthropic.AuthenticationError):
        make_reviewer(replying(error, status=401)).review_all([make_paper()])
