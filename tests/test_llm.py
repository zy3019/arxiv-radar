"""Drive the real SDKs against a fake HTTP transport.

These tests pin the requests we send and how we read replies. They do not prove a live
API accepts the request; only a run with a real key can do that.
"""

import json

import anthropic
import httpx2
import openai
import pytest

from arxiv_radar.config import LLMConfig
from arxiv_radar.llm import (
    FALLBACK_BETA,
    ClaudeReviewer,
    LLMError,
    OpenAICompatibleReviewer,
    make_reviewer,
)

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


def replying(*bodies, status=200, requests=None):
    """A transport handler that returns the bodies in turn, then repeats the last one."""
    queue = list(bodies)

    def handler(request):
        if requests is not None:
            requests.append(request)
        body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx2.Response(status, json=body)

    return handler


# --- OpenAI-compatible (DeepSeek) ---------------------------------------------------


def completion(content="", finish_reason="stop"):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


def openai_reviewer(handler, **llm_options):
    client = openai.OpenAI(
        api_key="test-key",
        base_url="https://api.test",
        max_retries=0,
        http_client=openai.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAICompatibleReviewer(LLMConfig(**llm_options), "RAG systems", "zh", client)


def openai_error(message="nope"):
    return {"error": {"message": message, "type": "invalid_request_error", "code": None}}


def test_openai_request_shape():
    requests = []
    reviewer = openai_reviewer(replying(completion(json.dumps(REVIEW)), requests=requests))

    reviewer.review(make_paper(title="Paper title", abstract="Paper abstract."))

    request = requests[0]
    body = json.loads(request.content)
    assert request.url.path.endswith("/chat/completions")
    assert request.headers["authorization"] == "Bearer test-key"
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    system, user = body["messages"]
    assert system["role"] == "system"
    assert "JSON" in system["content"]  # DeepSeek's JSON mode needs the word in the prompt
    assert "RAG systems" in system["content"]
    assert "Simplified Chinese" in system["content"]
    assert all(f'"{key}"' in system["content"] for key in REVIEW)
    assert "Paper title" in user["content"]
    assert "Paper abstract." in user["content"]


def test_openai_without_extra_body_sends_no_extra_fields():
    requests = []
    reviewer = openai_reviewer(
        replying(completion(json.dumps(REVIEW)), requests=requests), extra_body={}
    )

    reviewer.review(make_paper())

    assert "thinking" not in json.loads(requests[0].content)


def test_openai_parses_review_and_clamps_score():
    reply = completion(json.dumps({**REVIEW, "score": 0}))

    review = openai_reviewer(replying(reply)).review(make_paper())

    assert review.score == 1
    assert review.tags == ["RAG"]


def test_openai_retries_a_blank_reply_once():
    requests = []
    handler = replying(completion("   "), completion(json.dumps(REVIEW)), requests=requests)

    review = openai_reviewer(handler).review(make_paper())

    assert review.score == 8
    assert len(requests) == 2


def test_openai_gives_up_after_two_bad_replies():
    requests = []
    handler = replying(completion('{"score": 8}'), requests=requests)

    assert openai_reviewer(handler).review(make_paper()) is None
    assert len(requests) == 2


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
def test_openai_cut_off_or_filtered_reply_is_skipped(finish_reason):
    reply = completion('{"score": 8, "ti', finish_reason=finish_reason)

    assert openai_reviewer(replying(reply)).review(make_paper()) is None


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_openai_per_paper_errors_skip_the_paper(status):
    reviewer = openai_reviewer(replying(openai_error(), status=status))

    assert reviewer.review(make_paper()) is None


@pytest.mark.parametrize("status", [401, 402, 403, 404, 422])
def test_openai_setup_errors_abort_the_run(status):
    reviewer = openai_reviewer(replying(openai_error(), status=status))

    with pytest.raises(LLMError):
        reviewer.review(make_paper())


def test_openai_insufficient_balance_says_so():
    reviewer = openai_reviewer(replying(openai_error(), status=402))

    with pytest.raises(LLMError, match="balance"):
        reviewer.review(make_paper())


def test_openai_connection_failure_skips_the_paper():
    def handler(request):
        raise httpx2.ConnectError("refused")

    assert openai_reviewer(handler).review(make_paper()) is None


# --- batch behaviour ----------------------------------------------------------------


def test_review_all_keeps_successes_and_drops_failures():
    def handler(request):
        content = json.loads(request.content)["messages"][1]["content"]
        if "bad" in content:
            return httpx2.Response(200, json=completion(finish_reason="content_filter"))
        return httpx2.Response(200, json=completion(json.dumps(REVIEW)))

    papers = [
        make_paper("good1", abstract="fine"),
        make_paper("bad", abstract="bad"),
        make_paper("good2", abstract="fine"),
    ]

    assert set(openai_reviewer(handler).review_all(papers)) == {"good1", "good2"}


def test_review_all_raises_when_every_paper_fails():
    reviewer = openai_reviewer(replying(openai_error("unknown field"), status=400))
    papers = [make_paper(str(i)) for i in range(3)]

    with pytest.raises(LLMError, match="unknown field"):
        reviewer.review_all(papers)


def test_review_all_tolerates_a_lone_failure():
    reviewer = openai_reviewer(replying(openai_error(), status=400))

    assert reviewer.review_all([make_paper()]) == {}


def test_review_all_propagates_setup_errors():
    reviewer = openai_reviewer(replying(openai_error(), status=401))

    with pytest.raises(LLMError):
        reviewer.review_all([make_paper()])


# --- Claude -------------------------------------------------------------------------


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


def claude_reviewer(handler, **llm_options):
    client = anthropic.Anthropic(
        api_key="test-key",
        base_url="https://api.test",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    config = LLMConfig(provider="anthropic", **llm_options)
    return ClaudeReviewer(config, "RAG systems", "zh", client)


def claude_error(error_type="invalid_request_error"):
    return {"type": "error", "error": {"type": error_type, "message": "nope"}}


def test_claude_request_shape():
    requests = []
    reviewer = claude_reviewer(replying(message(json.dumps(REVIEW)), requests=requests))

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
    assert "Paper title" in body["messages"][0]["content"]


@pytest.mark.parametrize(
    "options",
    [{"model": "claude-haiku-5-5"}, {"refusal_fallback": False}],
    ids=["model-without-fallback", "turned-off"],
)
def test_claude_fallbacks_are_left_out_when_not_applicable(options):
    requests = []
    reviewer = claude_reviewer(
        replying(message(json.dumps(REVIEW)), requests=requests), **options
    )

    reviewer.review(make_paper())

    assert "fallbacks" not in json.loads(requests[0].content)
    assert FALLBACK_BETA not in requests[0].headers.get("anthropic-beta", "")


def test_claude_parses_review():
    review = claude_reviewer(replying(message(json.dumps(REVIEW)))).review(make_paper())

    assert review.score == 8


def test_claude_refusal_returns_none():
    reply = message(
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )

    assert claude_reviewer(replying(reply)).review(make_paper()) is None


def test_claude_truncated_reply_returns_none():
    reply = message('{"score": 8, "title_tr', stop_reason="max_tokens")

    assert claude_reviewer(replying(reply)).review(make_paper()) is None


@pytest.mark.parametrize("status", [429, 500, 529])
def test_claude_transient_errors_skip_the_paper(status):
    reviewer = claude_reviewer(replying(claude_error("api_error"), status=status))

    assert reviewer.review(make_paper()) is None


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_claude_setup_errors_abort_the_run(status):
    reviewer = claude_reviewer(replying(claude_error(), status=status))

    with pytest.raises(LLMError):
        reviewer.review(make_paper())


# --- factory ------------------------------------------------------------------------


def test_make_reviewer_picks_the_provider():
    deepseek = make_reviewer(LLMConfig(), "RAG", "zh", "key")
    claude = make_reviewer(LLMConfig(provider="anthropic"), "RAG", "zh", "key")

    assert isinstance(deepseek, OpenAICompatibleReviewer)
    assert str(deepseek.client.base_url).startswith("https://api.deepseek.com")
    assert isinstance(claude, ClaudeReviewer)
