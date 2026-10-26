"""A campaign's AI settings, request log and usage pages (DM + admins only, never shared between
campaigns), and the gateway that logs every call in detail."""

import urllib.error
from datetime import timedelta
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import crypto, gateway, urlcheck, usage
from apps.campaigns.models import Campaign
from apps.conftest import default_campaign, make_dm
from apps.frontend import llm


@pytest.fixture(autouse=True)
def admins():
    with override_settings(ADMIN_ACCOUNTS=["boss"]):
        yield


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    """No real name lookups: a host counts as public unless it says `local`."""
    monkeypatch.setattr(urlcheck, "is_public", lambda url: "local" not in url)


@pytest.fixture
def campaign(db):
    return default_campaign()


@pytest.fixture
def boss(db):
    return get_user_model().objects.create_user("boss")


@pytest.fixture
def dm(campaign):
    user = get_user_model().objects.create_user("dora")
    make_dm(user, campaign)
    return user


@pytest.fixture
def player(db):
    return get_user_model().objects.create_user("pip")


def _configure(campaign, key="sekrit", url="http://llm.local/v1"):
    config = AISettings.for_campaign(campaign)
    config.enabled = True
    config.base_url = url
    config.model = "m"
    config.api_key_encrypted = crypto.encrypt(key)
    config.allow_private_url = True
    config.save()
    return config


def _form(**overrides):
    data = {
        "enabled": "on",
        "use_tools": "on",
        "base_url": "https://api.example.com/v1/",
        "model": "gpt-x",
        "api_key": "super-secret-key",
        "system_prompt_extra": "",
        "max_context_chars": "50000",
        "daily_message_cap": "10",
        "log_retention_days": "30",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def test_key_round_trips_and_is_not_stored_in_clear():
    token = crypto.encrypt("sekrit")
    assert "sekrit" not in token
    assert crypto.decrypt(token) == "sekrit"
    assert crypto.decrypt("garbage") == ""


def test_pages_are_for_the_dm_and_admins_only(client, campaign, dm, player, boss):
    urls = [
        f"/campaigns/{campaign.pk}/ai/",
        f"/campaigns/{campaign.pk}/ai/requests/",
        f"/campaigns/{campaign.pk}/ai/usage/",
    ]
    client.force_login(player)
    for url in urls:
        assert client.get(url).status_code == 404
    assert client.post(f"/campaigns/{campaign.pk}/ai/test/").status_code == 404
    assert client.post(f"/campaigns/{campaign.pk}/ai/models/").status_code == 404
    for user in (dm, boss):
        client.force_login(user)
        for url in urls:
            assert client.get(url).status_code == 200
    # the DM of one campaign has no say in another
    other = Campaign.objects.create(name="Other")
    client.force_login(dm)
    assert client.get(f"/campaigns/{other.pk}/ai/").status_code == 404
    client.logout()
    assert client.get(urls[0]).status_code == 404


def test_the_campaign_page_links_to_the_ai_pages_for_the_dm(client, campaign, dm, player):
    client.force_login(dm)
    assert (
        f"/campaigns/{campaign.pk}/ai/" in client.get(f"/campaigns/{campaign.pk}/").content.decode()
    )
    client.force_login(player)
    assert (
        f"/campaigns/{campaign.pk}/ai/"
        not in client.get(f"/campaigns/{campaign.pk}/").content.decode()
    )


def test_settings_belong_to_one_campaign_only(client, campaign, dm):
    other = Campaign.objects.create(name="Other")
    client.force_login(dm)
    assert client.post(f"/campaigns/{campaign.pk}/ai/", _form()).status_code == 302
    mine = AISettings.for_campaign(campaign)
    assert mine.is_ready and crypto.decrypt(mine.api_key_encrypted) == "super-secret-key"
    theirs = AISettings.for_campaign(other)
    assert not theirs.is_ready and not theirs.has_key and theirs.base_url == ""


def test_the_key_is_never_shown_again_and_blank_keeps_it(client, campaign, dm):
    client.force_login(dm)
    client.post(f"/campaigns/{campaign.pk}/ai/", _form())
    config = AISettings.for_campaign(campaign)
    page = client.get(f"/campaigns/{campaign.pk}/ai/").content.decode()
    assert "super-secret-key" not in page and config.api_key_encrypted not in page
    client.post(
        f"/campaigns/{campaign.pk}/ai/", _form(api_key="", base_url="https://api.example.com/v1")
    )
    assert crypto.decrypt(AISettings.for_campaign(campaign).api_key_encrypted) == "super-secret-key"
    client.post(
        f"/campaigns/{campaign.pk}/ai/",
        _form(api_key="", clear_key="on", base_url="https://api.example.com/v1"),
    )
    assert not AISettings.for_campaign(campaign).has_key


def test_invalid_settings_are_rejected(client, campaign, dm):
    client.force_login(dm)
    response = client.post(f"/campaigns/{campaign.pk}/ai/", _form(base_url="ftp://x"))
    assert response.status_code == 200 and AISettings.for_campaign(campaign).base_url == ""
    response = client.post(f"/campaigns/{campaign.pk}/ai/", _form(max_context_chars="10"))
    assert response.status_code == 200


def test_a_dm_cannot_aim_the_server_at_a_private_address(client, campaign, dm, boss):
    client.force_login(dm)
    response = client.post(f"/campaigns/{campaign.pk}/ai/", _form(base_url="http://db.local:5432"))
    assert response.status_code == 200 and AISettings.for_campaign(campaign).base_url == ""
    client.force_login(boss)  # an administrator may (e.g. a local Ollama)
    assert (
        client.post(
            f"/campaigns/{campaign.pk}/ai/", _form(base_url="http://ollama.local/v1")
        ).status_code
        == 302
    )
    assert AISettings.for_campaign(campaign).allow_private_url


def test_a_dm_must_retype_the_key_to_change_the_url(client, campaign, dm):
    _configure(campaign, url="https://api.example.com/v1")
    client.force_login(dm)
    response = client.post(
        f"/campaigns/{campaign.pk}/ai/", _form(api_key="", base_url="https://evil.example.org")
    )
    assert response.status_code == 200
    assert AISettings.for_campaign(campaign).base_url == "https://api.example.com/v1"
    ok = client.post(
        f"/campaigns/{campaign.pk}/ai/",
        _form(api_key="new-key", base_url="https://evil.example.org"),
    )
    assert ok.status_code == 302


def test_the_model_list_comes_from_the_endpoint(client, campaign, dm, monkeypatch):
    seen = {}

    def fake(base, key, timeout=30):
        seen.update(base=base, key=key)
        return ["gpt-a", "gpt-b"]

    monkeypatch.setattr(llm, "list_models", fake)
    client.force_login(dm)
    response = client.post(
        f"/campaigns/{campaign.pk}/ai/models/",
        {"base_url": "https://api.example.com/v1", "api_key": "typed"},
    )
    assert response.json() == {"models": ["gpt-a", "gpt-b"]}
    assert seen == {"base": "https://api.example.com/v1", "key": "typed"}

    # a saved key is not sent to a new address on a DM's say-so
    _configure(campaign, url="https://api.example.com/v1")
    response = client.post(
        f"/campaigns/{campaign.pk}/ai/models/", {"base_url": "https://evil.example.org"}
    )
    assert response.status_code == 400

    def boom(base, key, timeout=30):
        raise llm.LLMError("LLM returned HTTP 401", "GET x\nHTTP 401\nResponse body: bad key")

    monkeypatch.setattr(llm, "list_models", boom)
    assert client.post(f"/campaigns/{campaign.pk}/ai/models/", {}).status_code == 502
    assert "bad key" in AIRequestLog.objects.get().error_detail


def test_list_models_parses_the_providers_answer(monkeypatch):
    monkeypatch.setattr(
        llm,
        "_post_json",
        lambda *a, **k: {"data": [{"id": "b"}, {"id": "a"}, {"name": "c"}, "d", {}]},
    )
    assert llm.list_models("http://x/v1", "k") == ["a", "b", "c", "d"]


def test_http_errors_keep_their_detail_but_never_the_key(monkeypatch):
    def fake_open(self, request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {}, BytesIO(b'{"error": "bad key sekrit"}')
        )

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fake_open)
    with pytest.raises(llm.LLMError) as caught:
        llm.chat_message("http://llm.local/v1", "sekrit", "m", [])
    assert str(caught.value) == "LLM returned HTTP 401"
    detail = caught.value.detail
    assert "401" in detail and "bad key" in detail and "/chat/completions" in detail
    assert "sekrit" not in detail


def test_gateway_logs_a_successful_call(campaign, dm, monkeypatch):
    _configure(campaign)
    seen = {}

    def fake(base, key, model, messages, **kwargs):
        seen.update(base=base, key=key, model=model)
        usage_ = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return {"content": "hello"}, usage_

    monkeypatch.setattr(llm, "chat_message", fake)
    assert gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm) == "hello"
    assert seen == {"base": "http://llm.local/v1", "key": "sekrit", "model": "m"}
    log = AIRequestLog.objects.get()
    assert (log.username, log.status, log.total_tokens, log.response_text) == (
        "dora",
        "ok",
        15,
        "hello",
    )
    assert log.campaign == campaign and "sekrit" not in str(log.request_json)


def test_gateway_runs_tools_until_the_model_answers(campaign, dm, monkeypatch):
    _configure(campaign)
    calls = []
    answers = [
        (
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "search_handbook",
                            "arguments": '{"query": "fireball"}',
                        },
                    }
                ],
            },
            {"total_tokens": 10},
        ),
        ({"content": "Fireball is great."}, {"total_tokens": 12}),
    ]

    def fake(base, key, model, messages, tools=None, **kwargs):
        calls.append((len(messages), bool(tools)))
        return answers.pop(0)

    monkeypatch.setattr(llm, "chat_message", fake)
    reply = gateway.ask(
        [{"role": "user", "content": "q"}],
        campaign=campaign,
        user=dm,
        tools=[{"type": "function"}],
        run_tool=lambda name, args: f"{name}:{args['query']}",
    )
    assert reply == "Fireball is great." and calls == [(1, True), (3, True)]
    log = AIRequestLog.objects.get()
    assert log.total_tokens == 22
    assert [m["role"] for m in log.request_json] == ["user", "assistant", "tool"]
    assert log.request_json[2]["content"] == "search_handbook:fireball"


def test_a_failing_tool_is_reported_to_the_model_not_fatal(campaign, dm, monkeypatch):
    _configure(campaign)
    first = {
        "content": "",
        "tool_calls": [{"id": "c", "function": {"name": "boom", "arguments": "not json"}}],
    }
    answers = [(first, {}), ({"content": "done"}, {})]
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: answers.pop(0))
    assert (
        gateway.ask(
            [{"role": "user", "content": "q"}],
            campaign=campaign,
            tools=[{}],
            run_tool=lambda n, a: "",
        )
        == "done"
    )
    assert AIRequestLog.objects.get().request_json[-1]["content"].startswith("Error:")


def test_tools_are_not_offered_when_switched_off(campaign, monkeypatch):
    config = _configure(campaign)
    config.use_tools = False
    config.save()
    seen = []
    monkeypatch.setattr(
        llm,
        "chat_message",
        lambda b, k, m, msgs, tools=None, **kw: (seen.append(tools), ({"content": "x"}, {}))[1],
    )
    gateway.ask(
        [{"role": "user", "content": "q"}], campaign=campaign, tools=[{}], run_tool=lambda n, a: ""
    )
    assert seen == [None]


def test_gateway_logs_a_failure_in_detail_and_hides_it_from_the_user(campaign, dm, monkeypatch):
    _configure(campaign)

    def boom(*args, **kwargs):
        raise llm.LLMError(
            "LLM returned HTTP 500", "POST http://x\nHTTP 500\nResponse body: upstream down"
        )

    monkeypatch.setattr(llm, "chat_message", boom)
    with pytest.raises(gateway.AIUnavailable) as caught:
        gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm)
    assert "500" not in str(caught.value)
    log = AIRequestLog.objects.get()
    assert log.status == "error" and "500" in log.error and "upstream down" in log.error_detail
    assert log.request_json == [{"role": "user", "content": "hi"}]


def test_an_unexpected_exception_is_logged_with_its_traceback(campaign, dm, monkeypatch):
    _configure(campaign)

    def boom(*args, **kwargs):
        raise KeyError("surprise")

    monkeypatch.setattr(llm, "chat_message", boom)
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm)
    assert "Traceback" in AIRequestLog.objects.get().error_detail


def test_gateway_refuses_when_off_or_unconfigured_or_private(campaign, dm, monkeypatch):
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm)
    config = _configure(campaign)
    config.allow_private_url = False
    config.save()
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: ({"content": "x"}, {}))
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm)
    assert AIRequestLog.objects.get().error == "URL not allowed"


def test_connection_test_is_logged_and_reported(client, campaign, dm, monkeypatch):
    _configure(campaign)
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: ({"content": "ok"}, {}))
    client.force_login(dm)
    response = client.post(f"/campaigns/{campaign.pk}/ai/test/")
    assert response.status_code == 302 and "works" in response["Location"].replace("%20", " ")
    assert AIRequestLog.objects.get().purpose == "test"


def test_request_log_and_usage_pages_are_per_campaign(client, campaign, dm, monkeypatch):
    _configure(campaign)
    other = Campaign.objects.create(name="Other")
    _configure(other)
    monkeypatch.setattr(
        llm, "chat_message", lambda *a, **k: ({"content": "the answer"}, {"total_tokens": 7})
    )
    gateway.ask([{"role": "user", "content": "the question"}], campaign=campaign, user=dm)
    gateway.ask([{"role": "user", "content": "elsewhere"}], campaign=other, user=dm)
    client.force_login(dm)
    log = AIRequestLog.objects.get(campaign=campaign)
    listing = client.get(f"/campaigns/{campaign.pk}/ai/requests/").content.decode()
    assert "the answer" in listing and "dora" in listing
    assert (
        listing.count("/ai/requests/") >= 1
        and f"/ai/requests/{AIRequestLog.objects.get(campaign=other).pk}/" not in listing
    )
    detail = client.get(f"/campaigns/{campaign.pk}/ai/requests/{log.pk}/").content.decode()
    assert "the question" in detail and "the answer" in detail
    foreign = AIRequestLog.objects.get(campaign=other)
    assert client.get(f"/campaigns/{campaign.pk}/ai/requests/{foreign.pk}/").status_code == 404
    dashboard = client.get(f"/campaigns/{campaign.pk}/ai/usage/?period=all")
    assert dashboard.context["totals"]["requests"] == 1
    assert dashboard.context["users"][0]["tokens"] == 7


def test_the_detail_page_shows_the_error_detail(client, campaign, dm, monkeypatch):
    _configure(campaign)

    def boom(*args, **kwargs):
        raise llm.LLMError("LLM is unreachable", "ConnectionRefusedError: [Errno 111]")

    monkeypatch.setattr(llm, "chat_message", boom)
    with pytest.raises(gateway.AIUnavailable):
        gateway.ask([{"role": "user", "content": "hi"}], campaign=campaign, user=dm)
    client.force_login(dm)
    entry = AIRequestLog.objects.get()
    page = client.get(f"/campaigns/{campaign.pk}/ai/requests/{entry.pk}/").content.decode()
    assert "ConnectionRefusedError" in page


def test_prune_follows_each_campaigns_retention(campaign, dm, monkeypatch):
    other = Campaign.objects.create(name="Other")
    _configure(campaign).log_retention_days = 30
    AISettings.objects.filter(campaign=campaign).update(log_retention_days=30)
    _configure(other)
    AISettings.objects.filter(campaign=other).update(log_retention_days=0)
    monkeypatch.setattr(llm, "chat_message", lambda *a, **k: ({"content": "x"}, {}))
    for c in (campaign, other):
        gateway.ask([{"role": "user", "content": "a"}], campaign=c, user=dm)
    AIRequestLog.objects.update(created_at=timezone.now() - timedelta(days=120))
    assert usage.prune_logs() == 1
    assert AIRequestLog.objects.get().campaign == other
