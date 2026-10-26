"""Streaming from the provider (SSE parsing, tool-call fragments, pings), the interrupted-answer
log, display names in the logs, and the list of past chats."""

import json
import time

import pytest
from django.contrib.auth import get_user_model

from apps.ai.models import AIRequestLog, AISettings, ChatMessage, ChatThread
from apps.ai.services import chat, crypto, gateway, urlcheck
from apps.campaigns.models import Campaign
from apps.conftest import default_campaign
from apps.frontend import llm


class FakeResponse:
    def __init__(self, lines, content_type="text/event-stream"):
        self.lines = lines
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self.lines)

    def read(self, n=-1):
        return b"".join(self.lines)


def sse(*chunks):
    lines = [f"data: {json.dumps(c)}\n\n".encode() for c in chunks]
    return [*lines, b"data: [DONE]\n\n"]


def serve(monkeypatch, response):
    monkeypatch.setattr(
        "urllib.request.OpenerDirector.open", lambda self, req, timeout=None: response
    )


def run_stream():
    return list(llm.chat_stream("http://x/v1", "k", "m", [{"role": "user", "content": "q"}]))


def test_stream_yields_text_as_it_arrives_then_the_whole_message(monkeypatch):
    serve(
        monkeypatch,
        FakeResponse(
            sse(
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"choices": [], "usage": {"total_tokens": 9}},
            )
        ),
    )
    assert run_stream() == [
        ("delta", "Hel"),
        ("delta", "lo"),
        ("message", {"content": "Hello"}),
        ("usage", {"total_tokens": 9}),
    ]


def test_stream_assembles_tool_calls_from_fragments(monkeypatch):
    first = {"index": 0, "id": "c1", "function": {"name": "search_handbook", "arguments": '{"que'}}
    second = {"index": 0, "function": {"arguments": 'ry": "fire"}'}}
    serve(
        monkeypatch,
        FakeResponse(
            sse(
                {"choices": [{"delta": {"tool_calls": [first]}}]},
                {"choices": [{"delta": {"tool_calls": [second]}}]},
            )
        ),
    )
    events = run_stream()
    message = events[-1][1]
    assert message["content"] is None
    assert message["tool_calls"] == [
        {
            "id": "c1",
            "type": "function",
            "function": {"name": "search_handbook", "arguments": '{"query": "fire"}'},
        }
    ]


def test_a_provider_that_ignores_stream_still_works(monkeypatch):
    body = json.dumps(
        {"choices": [{"message": {"content": "whole"}}], "usage": {"total_tokens": 3}}
    )
    serve(monkeypatch, FakeResponse([body.encode()], content_type="application/json"))
    assert run_stream() == [
        ("delta", "whole"),
        ("message", {"content": "whole"}),
        ("usage", {"total_tokens": 3}),
    ]


def test_stream_errors_carry_the_detail(monkeypatch):
    import urllib.error
    from io import BytesIO

    def refuse(self, request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, BytesIO(b"slow down k"))

    monkeypatch.setattr("urllib.request.OpenerDirector.open", refuse)
    with pytest.raises(llm.LLMError) as caught:
        run_stream()
    assert "429" in caught.value.detail and "slow down ***" in caught.value.detail


def test_stream_retries_without_stream_options_when_rejected(monkeypatch):
    import urllib.error
    from io import BytesIO

    seen = []

    def fake_open(self, request, timeout=None):
        payload = json.loads(request.data)
        seen.append("stream_options" in payload)
        if "stream_options" in payload:
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad", {}, BytesIO(b"unknown field stream_options")
            )
        return FakeResponse(sse({"choices": [{"delta": {"content": "ok"}}]}))

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fake_open)
    assert run_stream()[-1] == ("message", {"content": "ok"})
    assert seen == [True, False]


def test_a_silent_model_produces_pings(monkeypatch):
    monkeypatch.setattr(llm, "PING_SECONDS", 0.05)

    class Slow(FakeResponse):
        def __iter__(self):
            time.sleep(0.2)
            return iter(sse({"choices": [{"delta": {"content": "late"}}]}))

    serve(monkeypatch, Slow([]))
    kinds = [kind for kind, _v in run_stream()]
    assert kinds.count("ping") >= 2 and "message" in kinds


# --- gateway / logs ------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    monkeypatch.setattr(urlcheck, "is_public", lambda url: True)


@pytest.fixture
def campaign(db):
    return default_campaign()


@pytest.fixture
def named(campaign):
    return get_user_model().objects.create_user("riky@gmail.com", first_name="Riccardo")


def configure(campaign):
    config = AISettings.for_campaign(campaign)
    config.enabled, config.base_url, config.model = True, "http://x/v1", "m"
    config.api_key_encrypted = crypto.encrypt("k")
    config.save()


def test_logs_carry_the_first_name_not_the_email(campaign, named, monkeypatch):
    configure(campaign)
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: ({"content": "x"}, {}))
    gateway.ask([{"role": "user", "content": "q"}], campaign=campaign, user=named)
    monkeypatch.setattr(
        llm, "chat_message", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("no"))
    )
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "q"}], campaign=campaign, user=named)
    assert set(AIRequestLog.objects.values_list("display_name", flat=True)) == {"Riccardo"}
    assert AIRequestLog.objects.first().username == "riky@gmail.com"


def test_the_log_pages_show_the_first_name(client, campaign, named, monkeypatch):
    from apps.conftest import make_dm

    make_dm(named, campaign)
    configure(campaign)
    monkeypatch.setattr(
        llm, "chat_message", lambda *a, **k: ({"content": "x"}, {"total_tokens": 4})
    )
    gateway.ask([{"role": "user", "content": "q"}], campaign=campaign, user=named)
    client.force_login(named)
    for path in ("requests/", "usage/?period=all", f"requests/{AIRequestLog.objects.get().pk}/"):
        html = client.get(f"/campaigns/{campaign.pk}/ai/{path}").content.decode()
        assert "Riccardo" in html
        assert "riky@gmail.com" not in html.replace("?user=riky%40gmail.com", "").replace(
            'value="riky@gmail.com"', ""
        )


def test_an_abandoned_stream_is_logged_as_interrupted(campaign, named, monkeypatch):
    configure(campaign)

    def slow(*args, **kwargs):
        yield ("delta", "partial")
        yield ("delta", "more")

    monkeypatch.setattr(llm, "chat_stream", slow)
    events = gateway.converse(
        [{"role": "user", "content": "q"}], campaign=campaign, user=named, stream=True
    )
    assert next(events) == ("delta", "partial")
    events.close()
    entry = AIRequestLog.objects.get()
    assert entry.status == "error" and "interrupted" in entry.error


# --- past chats ----------------------------------------------------------------------------------


@pytest.fixture
def ready(campaign):
    configure(campaign)


def talk(thread, *questions):
    for question in questions:
        ChatMessage.objects.create(thread=thread, role="user", content=question)
        ChatMessage.objects.create(thread=thread, role="assistant", content="answer to " + question)


def test_new_chat_reuses_an_empty_one_and_keeps_old_ones(named, campaign, ready):
    first = chat.current_thread(named, campaign)
    assert chat.new_thread(named, campaign) == first  # nothing said yet: no pile of empty chats
    talk(first, "What now?")
    second = chat.new_thread(named, campaign)
    assert second != first and ChatThread.objects.filter(user=named).count() == 2


def test_history_lists_chats_with_messages_newest_first(client, named, campaign, ready):
    old = chat.current_thread(named, campaign)
    talk(old, "First question about goblins", "More")
    new = chat.new_thread(named, campaign)
    talk(new, "Second chat")
    empty = chat.new_thread(named, campaign)
    rows = chat.history(named, campaign)
    assert [r["thread"] for r in rows] == [new, old] and empty not in [r["thread"] for r in rows]
    assert rows[1]["title"] == "First question about goblins" and rows[1]["count"] == 4

    client.force_login(named)
    page = client.get("/chat/history/").content.decode()
    assert "First question about goblins" in page and f"/chat/t/{old.pk}/" in page
    assert page.index("Second chat") < page.index("First question about goblins")
    opened = client.get(f"/chat/t/{old.pk}/").content.decode()
    assert "answer to First question about goblins" in opened
    assert f'data-thread="{old.pk}"' in opened and "Second chat" not in opened


def test_chats_are_private_and_deletable(client, named, campaign, ready):
    mine = chat.current_thread(named, campaign)
    talk(mine, "secret")
    other = get_user_model().objects.create_user("other@gmail.com")
    client.force_login(other)
    assert client.get(f"/chat/t/{mine.pk}/").status_code == 404
    assert client.post(f"/chat/t/{mine.pk}/delete/").status_code == 404
    assert client.post("/chat/send/", {"thread": mine.pk, "message": "hi"}).status_code == 404
    assert "secret" not in client.get("/chat/history/").content.decode()
    client.force_login(named)
    assert client.post(f"/chat/t/{mine.pk}/delete/").status_code == 302
    assert not ChatThread.objects.filter(pk=mine.pk).exists()


def test_a_thread_of_another_campaign_is_not_opened(client, named, campaign, ready):
    elsewhere = Campaign.objects.create(name="Elsewhere")
    thread = ChatThread.objects.create(user=named, campaign=elsewhere)
    client.force_login(named)
    assert client.get(f"/chat/t/{thread.pk}/").status_code == 404


def test_events_leave_the_server_as_they_happen_even_when_gzip_is_accepted(
    named, campaign, ready, monkeypatch
):
    """Through the real middleware stack (GZip included) as an ASGI app would serve it: the first
    bytes must be out long before the model has finished."""
    from asgiref.sync import async_to_sync
    from django.test import AsyncClient

    def slow_model(*args, **kwargs):
        yield ("delta", "first")
        time.sleep(0.4)
        yield ("delta", "second")
        yield ("message", {"content": "firstsecond"})

    monkeypatch.setattr(llm, "chat_stream", slow_model)
    thread = chat.current_thread(named, campaign)

    async def go():
        client = AsyncClient()
        await client.aforce_login(named)
        response = await client.post(
            "/chat/send/",
            {"thread": thread.pk, "message": "hi"},
            headers={"Accept-Encoding": "gzip, deflate, br"},
        )
        stamps = []
        async for chunk in response:
            stamps.append((time.monotonic(), chunk))
        return response, stamps

    response, stamps = async_to_sync(go)()
    assert not response.has_header("Content-Encoding") or response["Content-Encoding"] == "identity"
    text_events = [t for t, chunk in stamps if b"event: text" in chunk]
    done = [t for t, chunk in stamps if b"event: done" in chunk]
    assert text_events and done and done[0] - text_events[0] >= 0.3
    assert stamps[0][1] == b": open\n\n"
