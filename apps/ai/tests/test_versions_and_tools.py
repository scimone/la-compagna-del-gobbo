"""Gemini's thought signatures, the compact context and the on-demand campaign tools, answers kept
when the page is closed, and edited / resent questions as versions you can flip between."""

import datetime
import json

import pytest
from django.contrib.auth import get_user_model

from apps.ai.models import AIRequestLog, AISettings, ChatMessage
from apps.ai.services import chat, context, crypto, tools, urlcheck
from apps.builder.tests.conftest import build_character
from apps.campaigns.models import Campaign
from apps.characters.models import Character
from apps.frontend import llm
from apps.frontend.chat_views import step_html
from apps.frontend.models import LogEntry

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture(autouse=True)
def public(monkeypatch):
    monkeypatch.setattr(urlcheck, "is_public", lambda url: True)


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def hero(alice):
    character = build_character(alice, "fighter", name="Brienne")
    character.status = Character.STATUS_COMPLETE
    character.backstory = "Born in a salt mine, she swore an oath of vengeance."
    character.appearance = "Tall, a scar across the left eye."
    character.notes = "Owes the baker three silver."
    character.save()
    return character


@pytest.fixture
def configured(hero):
    config = AISettings.for_campaign(hero.campaign)
    config.enabled, config.base_url, config.model = True, "http://x/v1", "m"
    config.api_key_encrypted = crypto.encrypt("k")
    config.save()


@pytest.fixture
def model(monkeypatch):
    """A scripted model: each call to it pops the next answer; every call's messages are kept."""

    class Script:
        def __init__(self):
            self.answers = []
            self.seen = []

        def say(self, *texts):
            self.answers += list(texts)

    script = Script()

    def fake_stream(base, key, model_, messages, **kwargs):
        script.seen.append(json.loads(json.dumps(messages)))
        answer = script.answers.pop(0) if script.answers else "ok"
        message = answer if isinstance(answer, dict) else {"content": answer}
        if message.get("content"):
            yield ("delta", message["content"])
        yield ("message", message)

    def fake_message(base, key, model_, messages, **kwargs):
        events = list(fake_stream(base, key, model_, messages, **kwargs))
        return events[-1][1], {}

    monkeypatch.setattr(llm, "chat_stream", fake_stream)
    monkeypatch.setattr(llm, "chat_message", fake_message)
    return script


# --- Gemini's thought_signature ------------------------------------------------------------------


def test_a_tool_call_keeps_the_fields_the_client_does_not_know():
    """Gemini's OpenAI-compatible API puts `extra_content.google.thought_signature` on a tool call
    and answers HTTP 400 if the next request does not send it back."""
    calls = {}
    llm._merge_call(
        calls,
        {
            "index": 0,
            "id": "c1",
            "function": {"name": "search_handbook", "arguments": '{"query":'},
            "extra_content": {"google": {"thought_signature": "SIG-"}},
        },
    )
    llm._merge_call(
        calls,
        {
            "index": 0,
            "function": {"arguments": ' "fire"}'},
            "extra_content": {"google": {"thought_signature": "NATURE"}},
        },
    )
    call = calls[0]
    assert call["function"] == {"name": "search_handbook", "arguments": '{"query": "fire"}'}
    assert call["extra_content"] == {"google": {"thought_signature": "SIG-NATURE"}}


def test_the_signature_is_sent_back_with_the_tool_result(hero, configured, alice, model):
    signed = {
        "id": "c1",
        "type": "function",
        "function": {"name": "search_handbook", "arguments": '{"query": "fireball"}'},
        "extra_content": {"google": {"thought_signature": "SIG"}},
    }
    model.say({"content": None, "tool_calls": [signed]}, "done")
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "hi", stream=True)
    second_request = model.seen[1]
    assistant = next(m for m in second_request if m.get("tool_calls"))
    assert assistant["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "SIG"
    assert second_request[-1]["role"] == "tool"


# --- the compact context and the tools that fetch the rest ---------------------------------------


def test_the_prompt_leaves_out_backstory_and_points_to_the_tool(alice, hero):
    text = context.build(alice, hero.campaign, hero, language="en")
    assert "salt mine" not in text and "scar across" not in text and "baker" not in text
    assert "get_character_details" in text
    config = AISettings.for_campaign(hero.campaign)
    config.use_tools = False
    config.save()
    without_tools = context.build(alice, hero.campaign, hero, language="en")
    assert "Backstory (start): Born in a salt mine" in without_tools
    assert "get_character_details" not in without_tools


def test_character_details_on_demand(alice, hero):
    run = tools.runner(alice, hero.campaign)
    text, ui = run("get_character_details", {"character": "brienne"})
    assert "salt mine" in text and "scar across" in text and "baker" in text
    assert ui["kind"] == "character" and ui["url"] == f"/characters/{hero.pk}/"
    text, ui = run(
        "get_character_details", {"character": str(hero.pk), "sections": ["features", "inventory"]}
    )
    assert "Features:" in text and "Inventory:" in text and "salt mine" not in text
    text, ui = run("get_character_details", {"character": "Nobody"})
    assert text == "No such character." and ui["error"]


def test_character_details_respect_who_may_see_what(alice, hero):
    draft = build_character(alice, "wizard", name="Unfinished")
    draft.backstory = "A secret."
    draft.save()
    other = Campaign.objects.create(name="Elsewhere")
    stranger = Character.objects.create(name="Mordred", campaign=other, owner=alice)
    run = tools.runner(alice, hero.campaign)
    for name in (draft.name, stranger.name):
        assert run("get_character_details", {"character": name})[0] == "No such character."


def _entry(alice, campaign, day, title, text):
    return LogEntry.objects.create(
        author=alice, campaign=campaign, date=datetime.date(2026, 9, day), title=title, text=text
    )


def test_logbook_tools_search_and_read_this_campaigns_entries(alice, hero):
    old = _entry(
        alice, hero.campaign, 1, "The Bridge", "We met a troll named Gruk near the bridge."
    )
    _entry(alice, hero.campaign, 2, "The Inn", "Rest.")
    other = Campaign.objects.create(name="Elsewhere")
    secret = _entry(alice, other, 3, "Secret", "Gruk is a spy in the other campaign.")
    run = tools.runner(alice, hero.campaign)

    text, ui = run("search_logbook", {"query": "gruk"})
    assert f"#{old.pk}" in text and "Gruk" in text and "spy" not in text
    assert (
        ui["kind"] == "logbook_search" and ui["count"] == 1 and ui["hits"][0]["url"] == "/logbook/"
    )
    assert run("search_logbook", {"query": "zzzzz"})[0] == "No logbook entries found."

    text, ui = run("read_logbook_entry", {"id": old.pk})
    assert "We met a troll named Gruk" in text and ui["title"].endswith("The Bridge")
    assert run("read_logbook_entry", {"id": secret.pk})[0] == "No such logbook entry."


def test_old_logbook_entries_are_one_line_each_in_the_prompt(alice, hero):
    _entry(alice, hero.campaign, 1, "Ancient", "A" * 40_000)
    _entry(alice, hero.campaign, 2, "Recent", "The party reached the keep.")
    text = context.build(alice, hero.campaign, hero, language="en")
    assert "The party reached the keep." in text
    assert "A" * 500 not in text  # the old one is cut to a line
    assert "Older entries, one line each (1;" in text and "Ancient" in text


@pytest.mark.parametrize(
    ("kind", "extra", "needle"),
    [
        (
            "search",
            {
                "query": "fire",
                "count": 3,
                "hits": [{"name": "Fireball", "url": "/x/", "group": "S"}],
            },
            "Searched the handbook",
        ),
        ("read", {"url": "/world/spells/fireball/", "title": "Fireball"}, "Read"),
        (
            "character",
            {"query": "Brienne", "url": "/characters/1/", "title": "Brienne"},
            "Read about",
        ),
        (
            "logbook_search",
            {
                "query": "gruk",
                "count": 2,
                "hits": [{"name": "The Bridge", "url": "/logbook/", "group": "d"}],
            },
            "Searched the logbook",
        ),
        ("logbook_read", {"url": "/logbook/", "title": "The Bridge"}, "Read"),
    ],
)
def test_every_kind_of_lookup_has_a_visible_step(kind, extra, needle):
    step = {"id": "1", "kind": kind, "query": extra.get("query", ""), **extra}
    assert "step-running" in step_html(step, "running")
    done = step_html(step, "done")
    assert "step-done" in done and needle in done and '<a class="chip"' in done
    assert "step-error" in step_html(step, "error")


def test_tool_calls_become_steps_of_the_right_kind():
    for name, kind in {
        "get_character_details": "character",
        "search_logbook": "logbook_search",
        "read_logbook_entry": "logbook_read",
        "read_page": "read",
        "search_handbook": "search",
    }.items():
        assert chat._step({"id": "1", "name": name, "args": {}})["kind"] == kind


# --- closing the page mid-answer -----------------------------------------------------------------


def test_closing_the_page_keeps_what_was_written(alice, hero, configured, monkeypatch):
    def slow(*args, **kwargs):
        yield ("delta", "Try the ")
        yield ("delta", "[Fireball](/world/spells/fireball/) first")
        yield ("message", {"content": "never reached"})

    monkeypatch.setattr(llm, "chat_stream", slow)
    thread = chat.new_thread(alice, hero.campaign)
    events = chat.send_events(thread, "What now?", stream=True)
    assert next(events) == ("text", "Try the ")
    assert next(events)[1].startswith("Try the [Fireball]")
    events.close()  # the page went away

    thread.refresh_from_db()
    answer = thread.head
    assert answer.role == "assistant" and answer.partial
    assert answer.content.startswith("Try the [Fireball]")
    assert answer.parent.content == "What now?" and answer.parent.role == "user"
    assert AIRequestLog.objects.get().error.startswith("interrupted")


def test_a_cut_short_answer_is_marked_and_does_not_break_the_next_question(
    client, alice, hero, configured, model
):
    thread = chat.new_thread(alice, hero.campaign)
    first = ChatMessage.objects.create(thread=thread, role="user", content="Q1")
    cut = ChatMessage.objects.create(
        thread=thread, parent=first, role="assistant", content="", partial=True
    )
    thread.head = cut
    thread.save()
    client.force_login(alice)
    assert "The answer was cut short." in client.get("/chat/").content.decode()
    model.say("fine")
    chat.send(thread, "Q2", stream=True)
    roles = [m["role"] for m in model.seen[0]]
    assert roles == ["system", "user", "user"]
    assert model.seen[0][-1]["content"] == "Q2"


# --- versions ------------------------------------------------------------------------------------


def _questions(thread):
    return [m.content for m in chat.path(thread) if m.role == "user"]


def test_editing_a_question_makes_a_second_version_with_its_own_followups(
    alice, hero, configured, model
):
    thread = chat.new_thread(alice, hero.campaign)
    model.say("A1", "A2", "A2-edited")
    chat.send(thread, "Q1")
    chat.send(thread, "Q2")
    thread.refresh_from_db()
    q2 = chat.path(thread)[2]
    assert (q2.role, q2.content) == ("user", "Q2")

    edited = chat.send(thread, "Q2 reworded", replace=q2.pk)
    thread.refresh_from_db()
    assert _questions(thread) == ["Q1", "Q2 reworded"] and thread.head == edited
    # the model saw the turns *before* the edited question, not the old branch
    seen = model.seen[-1]
    assert [m["content"] for m in seen[1:]] == ["Q1", "A1", "Q2 reworded"]

    new_q2 = chat.path(thread)[2]
    assert chat.versions(new_q2) == {"index": 2, "total": 2, "prev": q2.pk, "next": None}
    assert chat.versions(q2)["index"] == 1 and chat.versions(q2)["next"] == new_q2.pk
    assert chat.versions(chat.path(thread)[0])["total"] == 1


def test_asking_again_resends_the_same_text_as_a_new_version(alice, hero, configured, model):
    thread = chat.new_thread(alice, hero.campaign)
    model.say("first try", "second try")
    chat.send(thread, "Q1")
    q1 = chat.path(thread)[0]
    again = chat.send(thread, "", replace=q1.pk)
    assert again.content == "second try" and model.seen[-1][-1]["content"] == "Q1"
    thread.refresh_from_db()
    assert chat.versions(chat.path(thread)[0])["total"] == 2
    assert ChatMessage.objects.filter(thread=thread, role="user", parent=None).count() == 2


def test_flipping_between_versions_shows_each_one_with_what_followed_it(
    alice, hero, configured, model
):
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "Q1")
    chat.send(thread, "Q2")
    thread.refresh_from_db()
    q1 = chat.path(thread)[0]
    chat.send(thread, "Q1 v2", replace=q1.pk)
    chat.send(thread, "Q2 v2")
    thread.refresh_from_db()
    assert _questions(thread) == ["Q1 v2", "Q2 v2"]

    chat.switch_version(thread, q1.pk)
    thread.refresh_from_db()
    assert _questions(thread) == ["Q1", "Q2"]  # the old version with *its* follow-up
    v2 = chat.versions(chat.path(thread)[0])["next"]
    chat.switch_version(thread, v2)
    thread.refresh_from_db()
    assert _questions(thread) == ["Q1 v2", "Q2 v2"]


def test_a_new_question_continues_the_version_being_shown(alice, hero, configured, model):
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "Q1")
    q1 = chat.path(thread)[0]
    chat.send(thread, "Q1 v2", replace=q1.pk)
    chat.send(thread, "after v2")
    thread.refresh_from_db()
    assert _questions(thread) == ["Q1 v2", "after v2"]
    assert [m["content"] for m in model.seen[-1][1:-1]] == ["Q1 v2", "ok"]


def test_only_your_own_questions_of_this_chat_can_be_replaced(alice, hero, configured, model):
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "Q1")
    answer = chat.path(thread)[1]
    with pytest.raises(chat.ChatError):
        chat.send(thread, "x", replace=answer.pk)  # an answer, not a question
    elsewhere = chat.ChatThread.objects.create(user=alice, campaign=hero.campaign)
    foreign = ChatMessage.objects.create(thread=elsewhere, role="user", content="other chat")
    with pytest.raises(chat.ChatError):
        chat.send(thread, "x", replace=foreign.pk)
    with pytest.raises(chat.ChatError):
        chat.switch_version(thread, foreign.pk)


def test_the_page_shows_versions_and_the_buttons_inside_the_bubbles(
    client, alice, hero, configured, model
):
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "Q1")
    q1 = chat.path(thread)[0]
    chat.send(thread, "Q1 v2", replace=q1.pk)
    client.force_login(alice)

    page = client.get("/chat/").content.decode()
    assert "2 / 2" in page and f'data-switch="{q1.pk}"' in page
    bubble = page.split('<div class="msg user"')[1].split('<div class="msg assistant"')[0]
    for button in ("data-copy-button", "data-edit-button", "data-resend-button"):
        assert button in bubble.split('<div class="bubble-foot">')[1].split("</div>")[0]
    assert bubble.index('class="bubble-foot"') > bubble.index('class="bubble-body"')

    fragment = client.get(f"/chat/t/{thread.pk}/log/").content.decode()
    assert fragment.startswith('<div class="msg user"') and "<html" not in fragment

    assert client.post("/chat/switch/", {"thread": thread.pk, "message": q1.pk}).status_code == 204
    assert "Q1 v2" not in client.get(f"/chat/t/{thread.pk}/log/").content.decode()
    assert client.post("/chat/switch/", {"thread": thread.pk, "message": 0}).status_code == 400
    other = get_user_model().objects.create_user("other")
    client.force_login(other)
    assert client.get(f"/chat/t/{thread.pk}/log/").status_code == 404
    assert client.post("/chat/switch/", {"thread": thread.pk, "message": q1.pk}).status_code == 404


def test_the_history_shows_the_version_being_read(alice, hero, configured, model):
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "Original question")
    q1 = chat.path(thread)[0]
    chat.send(thread, "Reworded question", replace=q1.pk)
    row = chat.history(alice, hero.campaign)[0]
    assert row["title"] == "Reworded question" and row["count"] == 2


def test_gateway_log_still_names_the_tools_in_the_transcript(alice, hero, configured, model):
    model.say(
        {
            "content": None,
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {
                        "name": "get_character_details",
                        "arguments": '{"character": "Brienne"}',
                    },
                }
            ],
        },
        "She was born in a salt mine.",
    )
    thread = chat.new_thread(alice, hero.campaign)
    answer = chat.send(thread, "Tell me about her past", stream=True)
    assert answer.activity[0]["kind"] == "character" and answer.activity[0]["title"] == "Brienne"
    log = AIRequestLog.objects.get()
    assert "salt mine" in log.request_json[-1]["content"]
