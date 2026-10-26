"""Admin-panel pages for the AI chat: settings (key, endpoint, model), the log of every request
made with the key, and per-user usage. Admin only - anyone else gets a 404."""

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.ai.models import AIRequestLog, AISettings
from apps.ai.services import gateway, settings_form, usage
from apps.frontend.admin_views import PAGE_SIZE, TIME_ZONE, _require_admin


def _page(request, template, context):
    response = render(request, template, {"back_url": reverse("admin-panel"), **context})
    add_never_cache_headers(response)
    return response


def ai_settings(request):
    _require_admin(request)
    errors, notice = [], ""
    if request.method == "POST":
        errors = settings_form.save(request.POST)
        if not errors:
            return redirect("admin-ai-settings")
    elif request.GET.get("tested"):
        notice = request.GET["tested"]
    return _page(
        request,
        "frontend/admin/ai_settings.html",
        {
            "page_title": _("AI settings"),
            "config": AISettings.load(),
            "form": request.POST if errors else None,
            "errors": errors,
            "notice": notice,
        },
    )


@require_POST
def ai_test(request):
    """One tiny completion with the saved settings, to see that they work (logged as a test)."""
    _require_admin(request)
    try:
        reply = gateway.ask(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            user=request.user,
            purpose=AIRequestLog.Purpose.TEST,
        )
        result = _("Connection works. The model said: %(reply)s") % {"reply": reply[:80]}
    except gateway.AIUnavailable as error:
        result = _("Connection failed: %(error)s") % {"error": error}
    return redirect(f"{reverse('admin-ai-settings')}?tested={result}")


def ai_requests(request):
    _require_admin(request)
    queryset = AIRequestLog.objects.all()
    selected = request.GET.get("user", "")
    status = request.GET.get("status", "")
    if selected:
        queryset = queryset.filter(username=selected)
    if status in AIRequestLog.Status.values:
        queryset = queryset.filter(status=status)
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    users = AIRequestLog.objects.order_by("username").values_list("username", flat=True).distinct()
    with timezone.override(TIME_ZONE):
        return _page(
            request,
            "frontend/admin/ai_requests.html",
            {
                "page_title": _("AI requests"),
                "page": page,
                "selected": selected,
                "status": status,
                "users": [u for u in users if u],
            },
        )


def ai_request_detail(request, pk):
    _require_admin(request)
    log = get_object_or_404(AIRequestLog, pk=pk)
    with timezone.override(TIME_ZONE):
        response = render(
            request,
            "frontend/admin/ai_request_detail.html",
            {
                "page_title": _("AI request"),
                "back_url": reverse("admin-ai-requests"),
                "log": log,
            },
        )
    add_never_cache_headers(response)
    return response


def ai_usage(request):
    _require_admin(request)
    period = request.GET.get("period", usage.DEFAULT_PERIOD)
    if period not in usage.PERIODS:
        period = usage.DEFAULT_PERIOD
    queryset = usage.period_queryset(period)
    with timezone.override(TIME_ZONE):
        return _page(
            request,
            "frontend/admin/ai_usage.html",
            {
                "page_title": _("AI usage"),
                "period": period,
                "periods": list(usage.PERIODS),
                "totals": usage.totals(queryset),
                "users": usage.per_user(queryset),
                "days": usage.per_day(queryset, TIME_ZONE),
            },
        )
