"""The assistant's context (logbook + characters, scoped and filtered), the chat service and the
Chat menu. The model itself is always faked."""

import datetime

import pytest
from django.contrib.auth import get_user_model

from apps.ai.models import AIRequestLog, AISettings, ChatMessage
from apps.ai.services import chat, context, crypto, handbook_tools, links
from apps.builder.tests.conftest import build_character
from apps.campaigns.models import Campaign, CampaignMembership
from apps.characters.models import Character
from apps.conftest import default_campaign
from apps.frontend import llm
from apps.frontend.models import LogEntry

pytestmark = pytest.mark.usefixtures("imported_rules")


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


@pytest.fixture
def hero(alice):
    character = build_character(alice, "fighter", name="Brienne")
    character.status = Character.STATUS_COMPLETE
    character.save()
    return character


@pytest.fixture
def configured(db):
    config = AISettings.for_campaign(default_campaign())
    config.enabled, config.base_url, config.model = True, "http://llm.local/v1", "m"
    config.allow_private_url = True
    config.api_key_encrypted = crypto.encrypt("sekrit")
    config.save()


@pytest.fixture
def replies(monkeypatch):
    """Fakes the model; collects the messages it was sent."""
    sent = []

    def fake(base, key, model, messages, **kwargs):
        sent.append(list(messages))
        return {"content": "You could **attack**."}, {"total_tokens": 20}

    monkeypatch.setattr(llm, "chat_message", fake)
    return sent


def test_context_holds_the_logbook_and_the_character_sheet(alice, hero):
    campaign = hero.campaign
    LogEntry.objects.create(
        author=alice,
        campaign=campaign,
        date=datetime.date(2026, 9, 1),
        title="The Bridge",
        text="We fought trolls.",
    )
    text = context.build(alice, campaign, hero, language="en")
    assert "The Bridge" in text and "We fought trolls." in text
    assert "### Brienne (the asking player's character)" in text
    assert "HP " in text and "AC " in text and "Attack:" in text
    assert "BEGIN LOGBOOK" in text and "Answer in English" in text


def test_context_leaves_out_drafts_and_other_campaigns(alice, hero):
    campaign = hero.campaign
    draft = build_character(alice, "wizard", name="Unfinished")
    other = Campaign.objects.create(name="Elsewhere")
    CampaignMembership.objects.get_or_create(
        campaign=other, user=alice, defaults={"role": "player"}
    )
    LogEntry.objects.create(
        author=alice,
        campaign=other,
        date=datetime.date(2026, 9, 2),
        title="Secret",
        text="Elsewhere text",
    )
    text = context.build(alice, campaign, hero, language="en")
    assert draft.name not in text
    assert "Elsewhere text" not in text


def test_context_keeps_the_newest_entries_when_too_long(alice, hero):
    config = AISettings.for_campaign(default_campaign())
    config.max_context_chars = 2000
    config.save()
    for day in range(1, 9):
        LogEntry.objects.create(
            author=alice,
            campaign=hero.campaign,
            date=datetime.date(2026, 9, day),
            title=f"Day {day}",
            text="x" * 600,
        )
    text = context.build(alice, hero.campaign, hero, language="en")
    assert "Day 8" in text and "Day 1" not in text
    assert "oldest entries are left out" in text


def test_sending_a_question_stores_both_sides_and_logs_the_call(alice, hero, configured, replies):
    thread = chat.new_thread(alice, hero.campaign)
    assert thread.character == hero  # defaults to the user's own character
    answer = chat.send(thread, "What should I do?")
    assert answer.content == "You could **attack**."
    assert list(thread.messages.values_list("role", flat=True)) == ["user", "assistant"]
    system, question = replies[0][0], replies[0][-1]
    assert system["role"] == "system" and "Brienne" in system["content"]
    assert question == {"role": "user", "content": "What should I do?"}
    log = AIRequestLog.objects.get()
    assert log.thread == thread and log.campaign == hero.campaign and log.total_tokens == 20

    chat.send(thread, "And then?")
    assert [m["role"] for m in replies[1]] == ["system", "user", "assistant", "user"]


def test_limits_and_refusals_store_nothing(alice, hero, configured, replies):
    thread = chat.new_thread(alice, hero.campaign)
    for bad in ("", "   ", "x" * (chat.MAX_QUESTION_CHARS + 1)):
        with pytest.raises(chat.ChatError):
            chat.send(thread, bad)
    config = AISettings.for_campaign(default_campaign())
    config.daily_message_cap = 1
    config.save()
    chat.send(thread, "one")
    with pytest.raises(chat.ChatError, match="limit"):
        chat.send(thread, "two")
    assert ChatMessage.objects.count() == 2 and len(replies) == 1


def test_per_minute_limit(alice, hero, configured, replies, monkeypatch):
    monkeypatch.setattr(chat, "MAX_PER_MINUTE", 2)
    thread = chat.new_thread(alice, hero.campaign)
    chat.send(thread, "a")
    chat.send(thread, "b")
    with pytest.raises(chat.ChatError, match="wait"):
        chat.send(thread, "c")


def test_a_failing_model_stores_no_question(alice, hero, configured, monkeypatch):
    def boom(*args, **kwargs):
        raise llm.LLMError("LLM is unreachable", "ConnectionRefusedError")

    monkeypatch.setattr(llm, "chat_message", boom)
    thread = chat.new_thread(alice, hero.campaign)
    with pytest.raises(chat.ChatError):
        chat.send(thread, "hello")
    assert ChatMessage.objects.count() == 0
    assert "ConnectionRefusedError" in AIRequestLog.objects.get().error_detail


@pytest.mark.no_default_campaign
def test_a_non_member_cannot_ask(db, configured, replies):
    carol = get_user_model().objects.create_user("carol")
    campaign = Campaign.objects.create(name="Private")
    thread = chat.ChatThread.objects.create(user=carol, campaign=campaign)
    with pytest.raises(chat.ChatError, match="not in"):
        chat.send(thread, "hi")
    assert replies == []


def test_the_chat_menu(client, alice, hero, configured, replies):
    client.force_login(alice)
    page = client.get("/chat/").content.decode()
    assert 'data-menu="chat"' in page and "Brienne" in page

    response = client.post("/chat/send/", {"message": "<b>hi</b>"})
    assert response.status_code == 200
    assert "<strong>attack</strong>" in response.json()["html"]
    assert "&lt;b&gt;hi" in client.get("/chat/").content.decode()  # the question is escaped

    assert client.post("/chat/send/", {"message": ""}).status_code == 400
    assert client.post("/chat/character/", {"character": ""}).status_code == 200
    assert client.post("/chat/new/").status_code == 302
    assert client.get("/chat/").content.decode().count('class="bubble') == 0


def test_the_menu_is_hidden_until_the_assistant_is_on(client, alice, hero):
    client.force_login(alice)
    assert client.get("/chat/").status_code == 404
    assert client.post("/chat/send/", {"message": "hi"}).status_code == 404
    assert 'data-menu="chat"' not in client.get("/characters/").content.decode()


def test_signed_out_visitors_are_sent_to_sign_in(client, db, configured):
    response = client.get("/chat/")
    assert response.status_code == 302 and "/account/" in response["Location"]
    assert client.post("/chat/send/", {"message": "hi"}).status_code == 404


def test_context_names_the_pages_the_assistant_may_link_to(alice, hero):
    text = context.build(alice, hero.campaign, hero, language="en")
    assert f"Page: /characters/{hero.pk}/" in text
    assert "Markdown links" in text and "search_handbook" in text
    config = AISettings.for_campaign(hero.campaign)
    config.use_tools = False
    config.save()
    assert "search_handbook" not in context.build(alice, hero.campaign, hero, language="en")


def test_replies_keep_only_links_to_real_pages(hero):
    spell = f"/characters/{hero.pk}/"
    text = (
        f"See [her sheet]({spell}), [Fireball](/world/spells/fireball/), "
        "[made up](/world/spells/) [web](https://evil.example/x) [js](javascript:alert(1)) "
        "[admin](/admin-panel/) [nowhere](/characters/nope/)"
    )
    cleaned = links.clean(text)
    assert f"[her sheet]({spell})" in cleaned and "[Fireball](/world/spells/fireball/)" in cleaned
    assert "[made up](/world/spells/)" in cleaned  # a real list page
    for gone in ("](https://", "](javascript", "](/admin-panel", "](/characters/nope"):
        assert gone not in cleaned
    assert "web" in cleaned and "admin" in cleaned


def test_the_tools_search_and_read_the_handbook(db):
    found = handbook_tools.run("search_handbook", {"query": "fireball"})
    assert "/world/spells/fireball/" in found and "Fireball" in found
    narrowed = handbook_tools.run("search_handbook", {"query": "fireball", "category": "items"})
    assert "/world/spells/fireball/" not in narrowed
    page = handbook_tools.run("read_page", {"path": "/world/spells/fireball/"})
    assert (
        page.startswith("# Fireball") and "level: 3" in page and "Higher-Level Spell Slot" in page
    )
    assert handbook_tools.run("read_page", {"path": "/nope/"}) == "No such page."
    assert handbook_tools.run("read_page", {"path": "/characters/1/"}).startswith("That page")
    assert handbook_tools.run("search_handbook", {"query": "x"}) == "Query too short."
    klass = handbook_tools.run("read_page", {"path": "/world/classes/fighter/"})
    assert "Class features" in klass and "/world/feats/feature/" in klass
    assert len(handbook_tools.run("read_page", {"path": "/world/classes/fighter/"})) <= 7100


def test_a_chat_can_use_tools_and_link_to_what_it_found(
    client, alice, hero, configured, monkeypatch
):
    answers = [
        (
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "search_handbook",
                            "arguments": '{"query": "fireball"}',
                        },
                    }
                ],
            },
            {},
        ),
        (
            {
                "content": "Try [Fireball](/world/spells/fireball/) or [a fake](https://evil.example/).",
            },
            {},
        ),
    ]
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: answers.pop(0))
    client.force_login(alice)
    html = client.post("/chat/send/", {"message": "Any good spells?"}).json()["html"]
    assert '<a href="/world/spells/fireball/"' in html
    assert "evil.example" not in html and "a fake" in html
    log = AIRequestLog.objects.get()
    assert [m["role"] for m in log.request_json][-2:] == ["assistant", "tool"]
    assert "/world/spells/fireball/" in log.request_json[-1]["content"]


def test_a_crash_while_building_the_context_is_logged_with_its_traceback(
    alice, hero, configured, replies, monkeypatch
):
    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(context, "build", boom)
    thread = chat.new_thread(alice, hero.campaign)
    with pytest.raises(chat.ChatError):
        chat.send(thread, "hello")
    entry = AIRequestLog.objects.get()
    assert entry.status == "error" and "kaboom" in entry.error_detail
    assert "Traceback" in entry.error_detail and replies == []


def test_the_assistant_is_per_campaign(client, alice, hero, configured):
    other = Campaign.objects.create(name="Elsewhere")
    CampaignMembership.objects.get_or_create(
        campaign=other, user=alice, defaults={"role": "player"}
    )
    assert chat.is_available(hero.campaign) and not chat.is_available(other)
    client.force_login(alice)
    session = client.session
    session["current_campaign"] = other.pk
    session.save()
    from apps.campaigns.services import membership

    session[membership.SESSION_KEY] = other.pk
    session.save()
    assert client.get("/chat/").status_code == 404
    assert 'data-menu="chat"' not in client.get("/characters/").content.decode()


def test_the_chat_item_is_the_last_one_in_the_bottom_nav(client, alice, hero, configured):
    client.force_login(alice)
    nav = (
        client.get("/characters/")
        .content.decode()
        .split('<nav class="bottom-nav">')[1]
        .split("</nav>")[0]
    )
    menus = [part.split('"')[0] for part in nav.split('data-menu="')[1:]]
    assert menus == ["characters", "logbook", "world", "chat"]
