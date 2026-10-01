"""Automatic translation of Logbook entries and backstories: the queue, what a page shows, the
worker, and the checks on what the language model hands back."""

import datetime
import io
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.frontend import llm, translations
from apps.frontend.management.commands import translate_worker
from apps.frontend.models import LogEntry, TranslationJob


@pytest.fixture
def alice(db):
    return get_user_model().objects.create_user("alice")


def _entry(alice, **fields):
    return LogEntry.objects.create(author=alice, date=datetime.date(2026, 9, 1), **fields)


def _finish(job, result):
    job.result, job.status = result, TranslationJob.DONE
    job.save()


def _it(client):
    client.cookies["django_language"] = "it"


def test_saving_in_italian_queues_an_english_translation(client, alice):
    client.force_login(alice)
    _it(client)

    client.post("/logbook/new/", {"date": "2026-09-01", "title": "Il drago", "text": ""})

    job = TranslationJob.objects.get()
    assert (job.source_lang, job.target_lang) == ("it", "en")
    assert job.source == {"title": "Il drago"}  # empty fields are not sent


def test_the_other_language_reads_the_translation_and_the_writer_the_original(client, alice):
    entry = _entry(alice, title="Il drago")
    job = translations.enqueue("logentry", entry.pk, {"title": "Il drago"}, source_lang="it")
    _finish(job, {"title": "The dragon"})

    english = client.get("/logbook/").content.decode()
    _it(client)
    italian = client.get("/logbook/").content.decode()

    assert (
        "The dragon" in english
        and "self-translated-badge" in english
        and ">Translation<" in english
    )
    assert "Il drago" in italian and "The dragon" not in italian


def test_an_edited_text_never_shows_its_old_translation(client, alice):
    entry = _entry(alice, title="Il drago")
    _finish(
        translations.enqueue("logentry", entry.pk, entry.title and {"title": "Il drago"}, "it"),
        {"title": "The dragon"},
    )
    entry.title = "Il lupo"
    entry.save()

    html = client.get("/logbook/").content.decode()

    assert "Il lupo" in html and "The dragon" not in html


def test_a_newer_job_replaces_one_still_waiting(alice):
    entry = _entry(alice, title="uno")
    translations.enqueue("logentry", entry.pk, {"title": "uno"}, "it")
    translations.enqueue("logentry", entry.pk, {"title": "due"}, "it")

    assert list(TranslationJob.objects.values_list("source", flat=True)) == [{"title": "due"}]


def test_the_queue_and_job_size_are_bounded(alice, monkeypatch):
    assert (
        translations.enqueue("logentry", 1, {"notes": "x" * 9000}, "it").source["notes"]
        == "x" * 8000
    )
    assert (
        translations.enqueue("logentry", 2, {f"f{i}": "y" * 5000 for i in range(5)}, "it") is None
    )
    monkeypatch.setattr(translations, "MAX_PENDING", 1)
    assert translations.enqueue("logentry", 3, {"title": "z"}, "it") is None


def test_search_finds_text_as_written_or_in_its_translation(client, alice):
    entry = _entry(alice, title="Il drago", text="Waterdeep")
    _entry(alice, title="Altro")
    _finish(
        translations.enqueue("logentry", entry.pk, {"title": "Il drago"}, "it"),
        {"title": "The dragon"},
    )

    # Read in English the entry shows its translation; the Italian original is searchable too.
    for q in ("drago", "dragon"):
        hit = client.get(f"/logbook/?q={q}").content.decode()
        assert "The <mark>" in hit and "Altro" not in hit
    assert "No entries match" in client.get("/logbook/?q=zzz").content.decode()
    assert "Waterdeep" in client.get("/logbook/?q=WATERDEEP").content.decode()


def test_backstory_edits_queue_a_translation_and_readers_see_it(client, alice):
    from apps.characters.models import Character

    character = Character.objects.create(
        owner=alice, name="Mira", status=Character.STATUS_COMPLETE, backstory="Nata a Neverwinter"
    )
    job = translations.enqueue("backstory", character.pk, {"backstory": character.backstory}, "it")
    _finish(job, {"backstory": "Born in Neverwinter"})

    shown = translations.translated_texts(
        "backstory", {character.pk: {"backstory": character.backstory}}, "en"
    )

    assert shown[character.pk]["backstory"] == ("Born in Neverwinter", True)


def test_the_worker_translates_and_gives_up_after_three_failures(alice, monkeypatch):
    ok = translations.enqueue("logentry", 1, {"title": "ciao"}, "it")
    monkeypatch.setattr(llm, "translate", lambda fields, s, t: {"title": "hello"})
    assert translate_worker.work_once() is True
    ok.refresh_from_db()
    assert ok.status == TranslationJob.DONE and ok.result == {"title": "hello"}

    bad = translations.enqueue("logentry", 2, {"title": "ciao"}, "it")

    def boom(fields, s, t):
        raise llm.TranslationError("LLM is unreachable")

    monkeypatch.setattr(llm, "translate", boom)
    while translate_worker.work_once():
        pass
    bad.refresh_from_db()
    assert bad.status == TranslationJob.FAILED and bad.attempts == 3


def test_the_worker_stops_at_its_hourly_budget(alice, monkeypatch):
    monkeypatch.setattr(translate_worker, "MAX_JOBS_PER_HOUR", 1)
    monkeypatch.setattr(llm, "translate", lambda fields, s, t: {"title": "x"})
    translations.enqueue("logentry", 1, {"title": "a"}, "it")
    translations.enqueue("logentry", 2, {"title": "b"}, "it")

    assert translate_worker.work_once() is True
    assert translate_worker.work_once() is False
    assert TranslationJob.objects.filter(status=TranslationJob.PENDING).count() == 1


def test_worker_command_drains_the_queue_with_once(alice, monkeypatch):
    monkeypatch.setattr(llm, "translate", lambda fields, s, t: {"title": "x"})
    translations.enqueue("logentry", 1, {"title": "a"}, "it")

    call_command("translate_worker", "--once")

    assert TranslationJob.objects.get().status == TranslationJob.DONE


# --- llm.translate: configuration and what it accepts back ------------------------------------


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _model_says(monkeypatch, content, captured=None):
    def fake_open(self, request, timeout=None):
        if captured is not None:
            captured["request"] = request
        return _Response(json.dumps({"choices": [{"message": {"content": content}}]}).encode())

    monkeypatch.setenv("LLM_BASE_URL", "http://llm.local:1234/v1/")
    monkeypatch.setenv("LLM_API_KEY", "sekrit")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", fake_open)


def test_llm_sends_the_text_as_json_data_and_parses_the_reply(monkeypatch):
    seen = {}
    _model_says(monkeypatch, '<think>hm</think>```json\n{"title": "Hello"}\n```', seen)

    assert llm.translate({"title": "Ciao"}, "it", "en") == {"title": "Hello"}

    request = seen["request"]
    body = json.loads(request.data)
    assert request.full_url == "http://llm.local:1234/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer sekrit"
    assert json.loads(body["messages"][1]["content"]) == {"title": "Ciao"}
    assert "DATA" in body["messages"][0]["content"] and "English" in body["messages"][0]["content"]


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[1, 2]",
        '{"other": "x"}',
        '{"title": 5}',
        '{"title": ""}',
        json.dumps({"title": "x" * 500}),
    ],
)
def test_llm_rejects_malformed_or_implausible_replies(monkeypatch, reply):
    _model_says(monkeypatch, reply)

    with pytest.raises(llm.TranslationError):
        llm.translate({"title": "Ciao"}, "it", "en")


def test_llm_needs_configuration_and_never_leaks_the_key(monkeypatch):
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(llm.TranslationError, match="not configured"):
        llm.translate({"title": "a"}, "it", "en")

    monkeypatch.setenv("LLM_BASE_URL", "file:///etc/passwd")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_API_KEY", "sekrit")
    with pytest.raises(llm.TranslationError, match="not configured"):
        llm.translate({"title": "a"}, "it", "en")

    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    with pytest.raises(llm.TranslationError) as error:
        llm.translate({"title": "a"}, "it", "en")
    assert "sekrit" not in str(error.value)


def test_the_web_container_is_given_no_llm_credentials():
    from pathlib import Path

    compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text()
    web = compose.split("dnd-translator:")[0]
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        assert f'{name}: ""' in web


def test_a_search_marks_the_matches_in_the_shown_text_escaped(client, alice):
    _entry(alice, title="Il Drago <b>", text="Un drago rosso. Il DRAGO dorme.")

    html = client.get("/logbook/?q=drago").content.decode()

    assert html.count("<mark>") == 3
    assert "<mark>Drago</mark> &lt;b&gt;" in html and "<mark>DRAGO</mark> dorme" in html
    assert "<b>" not in html.split('id="search-results"')[1]


def test_editing_the_translated_version_overwrites_the_original(client, alice):
    entry = _entry(alice, title="Il drago", text="Waterdeep")
    _finish(
        translations.enqueue(
            "logentry", entry.pk, {"title": "Il drago", "text": "Waterdeep"}, "it"
        ),
        {"title": "The dragon", "text": "Waterdeep"},
    )
    client.force_login(alice)  # reading English: the form starts from the translation
    html = client.get(f"/logbook/{entry.pk}/edit/").content.decode()
    assert 'value="The dragon"' in html

    client.post(
        f"/logbook/{entry.pk}/edit/",
        {"date": "2026-09-01", "title": "The red dragon", "text": "Waterdeep"},
    )

    entry.refresh_from_db()
    assert entry.title == "The red dragon"  # the Italian original is gone
    job = TranslationJob.objects.filter(status=TranslationJob.PENDING).get()
    assert (job.source_lang, job.target_lang) == ("en", "it")
    assert job.source["title"] == "The red dragon"


def test_saving_an_unchanged_translated_form_keeps_the_original(client, alice):
    entry = _entry(alice, title="Il drago")
    _finish(
        translations.enqueue("logentry", entry.pk, {"title": "Il drago"}, "it"),
        {"title": "The dragon"},
    )
    client.force_login(alice)

    client.post(f"/logbook/{entry.pk}/edit/", {"date": "2026-09-01", "title": "The dragon"})

    entry.refresh_from_db()
    assert entry.title == "Il drago"
    assert not TranslationJob.objects.filter(status=TranslationJob.PENDING).exists()
