"""A campaign's AI pages - settings (endpoint, model, key), the log of every request made with
its key, and per-user usage. For the campaign's DM and administrators; anyone else gets a 404."""

from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import crypto, gateway, settings_form, urlcheck, usage
from apps.campaigns.models import Campaign
from apps.campaigns.services import membership
from apps.frontend import llm
from apps.frontend.admin_views import PAGE_SIZE, TIME_ZONE


def _managed(request, pk) -> Campaign:
    campaign = get_object_or_404(Campaign, pk=pk)
    if not request.user.is_authenticated or not membership.can_manage(request.user, campaign):
        raise Http404
    return campaign


def _page(request, campaign, template, context):
    response = render(
        request,
        template,
        {
            "back_url": reverse("campaign-detail", args=[campaign.pk]),
            "campaign": campaign,
            **context,
        },
    )
    add_never_cache_headers(response)
    return response


def ai_settings(request, pk):
    campaign = _managed(request, pk)
    config = AISettings.for_campaign(campaign)
    errors, notice = [], ""
    if request.method == "POST":
        errors = settings_form.save(
            config, request.POST, by_admin=membership.is_admin(request.user)
        )
        if not errors:
            return redirect("campaign-ai", pk=campaign.pk)
    else:
        notice = request.GET.get("tested", "")
    return _page(
        request,
        campaign,
        "frontend/campaigns/ai_settings.html",
        {
            "page_title": _("AI assistant"),
            "config": config,
            "form": request.POST if errors else None,
            "errors": errors,
            "notice": notice,
        },
    )


@require_POST
def ai_test(request, pk):
    """One tiny completion with the saved settings, to see that they work (logged as a test)."""
    campaign = _managed(request, pk)
    try:
        reply = gateway.ask(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            campaign=campaign,
            user=request.user,
            purpose=AIRequestLog.Purpose.TEST,
        )
        result = _("Connection works. The model said: %(reply)s") % {"reply": reply[:80]}
    except gateway.AIUnavailable as error:
        result = _("Connection failed: %(error)s") % {"error": error}
    return redirect(f"{reverse('campaign-ai', args=[campaign.pk])}?tested={result}")


@require_POST
def ai_models(request, pk):
    """The model ids the typed (or saved) endpoint offers, for the settings form's picker. The
    key is the typed one, else the saved one; nothing is stored."""
    campaign = _managed(request, pk)
    config = AISettings.for_campaign(campaign)
    base = request.POST.get("base_url", "").strip().rstrip("/") or config.base_url
    typed = request.POST.get("api_key", "").strip()
    saved_url = base == config.base_url
    # A saved key is only ever sent to the saved address, or by an administrator.
    if not typed and not (saved_url or membership.is_admin(request.user)):
        return JsonResponse({"error": _("Enter the API key to load the models.")}, status=400)
    key = typed or crypto.decrypt(config.api_key_encrypted)
    if not base:
        return JsonResponse({"error": _("Enter the base URL first.")}, status=400)
    private_ok = membership.is_admin(request.user) or (saved_url and config.allow_private_url)
    if not private_ok and not urlcheck.is_public(base):
        return JsonResponse(
            {"error": _("That address is not reachable from the internet.")}, status=400
        )
    try:
        models = llm.list_models(base, key)
    except llm.LLMError as error:
        gateway.log_failure(
            campaign,
            user=request.user,
            purpose=AIRequestLog.Purpose.TEST,
            messages=[{"role": "system", "content": f"GET {base}/models"}],
            error=f"listing models: {error}",
            detail=getattr(error, "detail", ""),
        )
        return JsonResponse(
            {"error": _("Could not load the models: %(error)s") % {"error": error}}, status=502
        )
    return JsonResponse({"models": models})


def ai_requests(request, pk):
    campaign = _managed(request, pk)
    queryset = AIRequestLog.objects.filter(campaign=campaign)
    selected = request.GET.get("user", "")
    status = request.GET.get("status", "")
    if selected:
        queryset = queryset.filter(username=selected)
    if status in AIRequestLog.Status.values:
        queryset = queryset.filter(status=status)
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    users = (
        AIRequestLog.objects.filter(campaign=campaign)
        .order_by("username")
        .values_list("username", flat=True)
        .distinct()
    )
    with timezone.override(TIME_ZONE):
        return _page(
            request,
            campaign,
            "frontend/campaigns/ai_requests.html",
            {
                "page_title": _("AI requests"),
                "page": page,
                "selected": selected,
                "status": status,
                "users": [u for u in users if u],
            },
        )


def ai_request_detail(request, pk, log_pk):
    campaign = _managed(request, pk)
    entry = get_object_or_404(AIRequestLog, pk=log_pk, campaign=campaign)
    with timezone.override(TIME_ZONE):
        response = render(
            request,
            "frontend/campaigns/ai_request_detail.html",
            {
                "page_title": _("AI request"),
                "back_url": reverse("campaign-ai-requests", args=[campaign.pk]),
                "campaign": campaign,
                "log": entry,
                "transcript": [_message_view(m) for m in entry.request_json],
            },
        )
    add_never_cache_headers(response)
    return response


def _message_view(message: dict) -> dict:
    """One message of a stored request for the detail page: its text, plus any tool calls."""
    calls = [
        f"{c.get('function', {}).get('name', '?')}({c.get('function', {}).get('arguments', '')})"
        for c in message.get("tool_calls") or []
        if isinstance(c, dict)
    ]
    return {
        "role": message.get("role", "?"),
        "content": str(message.get("content") or ""),
        "calls": calls,
    }


def ai_usage(request, pk):
    campaign = _managed(request, pk)
    period = request.GET.get("period", usage.DEFAULT_PERIOD)
    if period not in usage.PERIODS:
        period = usage.DEFAULT_PERIOD
    queryset = usage.period_queryset(campaign, period)
    with timezone.override(TIME_ZONE):
        return _page(
            request,
            campaign,
            "frontend/campaigns/ai_usage.html",
            {
                "page_title": _("AI usage"),
                "period": period,
                "periods": list(usage.PERIODS),
                "totals": usage.totals(queryset),
                "users": usage.per_user(queryset),
                "days": usage.per_day(queryset, TIME_ZONE),
            },
        )
