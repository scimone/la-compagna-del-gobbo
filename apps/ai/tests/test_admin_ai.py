"""AI settings, the request log and usage in the admin panel; the gateway that logs every call."""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import crypto, gateway, usage
from apps.frontend import llm


@pytest.fixture(autouse=True)
def admins():
    with override_settings(ADMIN_ACCOUNTS=["boss"]):
        yield


@pytest.fixture
def boss(client, db):
    user = get_user_model().objects.create_user("boss")
    client.force_login(user)
    return user


def _configure(key="sekrit"):
    config = AISettings.load()
    config.enabled = True
    config.base_url = "http://llm.local/v1"
    config.model = "m"
    config.api_key_encrypted = crypto.encrypt(key)
    config.save()


def test_key_round_trips_and_is_not_stored_in_clear():
    token = crypto.encrypt("sekrit")
    assert "sekrit" not in token
    assert crypto.decrypt(token) == "sekrit"
    assert crypto.decrypt("garbage") == ""


def test_pages_are_admin_only(client, db):
    alice = get_user_model().objects.create_user("alice")
    client.force_login(alice)
    for url in ("/admin-panel/ai/", "/admin-panel/ai/requests/", "/admin-panel/ai/usage/"):
        assert client.get(url).status_code == 404
    assert client.post("/admin-panel/ai/test/").status_code == 404


def test_settings_are_saved_and_the_key_is_never_shown_again(client, boss):
    response = client.post(
        "/admin-panel/ai/",
        {
            "enabled": "on",
            "base_url": "https://api.example.com/v1/",
            "model": "gpt-x",
            "api_key": "super-secret-key",
            "system_prompt_extra": "",
            "max_context_chars": "50000",
            "daily_message_cap": "10",
            "log_retention_days": "30",
        },
    )
    assert response.status_code == 302
    config = AISettings.load()
    assert config.enabled and config.base_url == "https://api.example.com/v1"
    assert crypto.decrypt(config.api_key_encrypted) == "super-secret-key"
    page = client.get("/admin-panel/ai/").content.decode()
    assert "super-secret-key" not in page and config.api_key_encrypted not in page

    # a blank key field keeps the stored key
    client.post(
        "/admin-panel/ai/",
        {
            "base_url": "https://x.org",
            "model": "m",
            "max_context_chars": "5000",
            "daily_message_cap": "0",
            "log_retention_days": "0",
        },
    )
    assert crypto.decrypt(AISettings.load().api_key_encrypted) == "super-secret-key"


def test_invalid_settings_are_rejected(client, boss):
    response = client.post(
        "/admin-panel/ai/",
        {
            "base_url": "ftp://x",
            "max_context_chars": "5000",
            "daily_message_cap": "0",
            "log_retention_days": "0",
        },
    )
    assert response.status_code == 200
    assert AISettings.load().base_url == ""


def test_gateway_logs_a_successful_call(boss, monkeypatch):
    _configure()
    seen = {}

    def fake(base, key, model, messages, **kwargs):
        seen.update(base=base, key=key, model=model)
        return "hello", {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    monkeypatch.setattr(llm, "chat_completion", fake)
    assert gateway.ask([{"role": "user", "content": "hi"}], user=boss) == "hello"
    assert seen == {"base": "http://llm.local/v1", "key": "sekrit", "model": "m"}
    log = AIRequestLog.objects.get()
    assert (log.username, log.status, log.total_tokens, log.response_text) == (
        "boss",
        "ok",
        15,
        "hello",
    )
    assert log.request_json == [{"role": "user", "content": "hi"}]
    assert "sekrit" not in str(log.request_json)


def test_gateway_logs_a_failure_and_hides_the_detail(boss, monkeypatch):
    _configure()

    def boom(*args, **kwargs):
        raise llm.LLMError("LLM returned HTTP 500")

    monkeypatch.setattr(llm, "chat_completion", boom)
    with pytest.raises(gateway.AIUnavailable) as caught:
        gateway.ask([{"role": "user", "content": "hi"}], user=boss)
    assert "500" not in str(caught.value)
    log = AIRequestLog.objects.get()
    assert log.status == "error" and "500" in log.error


def test_gateway_refuses_when_off_or_unconfigured(boss):
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "hi"}], user=boss)
    assert AIRequestLog.objects.count() == 0


def test_request_log_and_usage_pages(client, boss, monkeypatch):
    _configure()
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: ("the answer", {"total_tokens": 7}))
    gateway.ask([{"role": "user", "content": "the question"}], user=boss)
    log = AIRequestLog.objects.get()
    listing = client.get("/admin-panel/ai/requests/").content.decode()
    assert "the answer" in listing and "boss" in listing
    detail = client.get(f"/admin-panel/ai/requests/{log.pk}/").content.decode()
    assert "the question" in detail and "the answer" in detail
    dashboard = client.get("/admin-panel/ai/usage/?period=all")
    assert dashboard.status_code == 200
    assert dashboard.context["totals"]["requests"] == 1
    assert dashboard.context["users"][0]["username"] == "boss"
    assert dashboard.context["users"][0]["tokens"] == 7


def test_prune_deletes_old_logs(boss, monkeypatch):
    from datetime import timedelta

    from django.utils import timezone

    _configure()
    monkeypatch.setattr(llm, "chat_completion", lambda *a, **k: ("x", {}))
    gateway.ask([{"role": "user", "content": "a"}], user=boss)
    AIRequestLog.objects.update(created_at=timezone.now() - timedelta(days=120))
    gateway.ask([{"role": "user", "content": "b"}], user=boss)
    assert usage.prune_logs() == 1
    assert AIRequestLog.objects.count() == 1
