"""The Logbook menu: the party's shared journal, a vertical timeline of session entries."""

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.frontend import logbook
from apps.frontend.entries_render import machine_translated_badge
from apps.frontend.forms import LogEntryForm
from apps.frontend.handbook_search import highlight, query_pattern
from apps.frontend.models import LogEntry


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


def logbook_list(request):
    q = request.GET.get("q", "").strip()
    found = list(logbook.list_entries())
    if q:
        found = logbook.search(found, q)
    shown = logbook.display(found)
    pattern = query_pattern(q) if q else None

    def mark(text):
        return highlight(text, pattern) if pattern else text

    entries = [
        {
            "entry": entry,
            "can_edit": logbook.can_edit(request.user, entry),
            "fields": {name: mark(text) for name, (text, _t) in shown[entry.pk].items()},
            "author_name": mark(entry.author.get_username()) if entry.author else "",
            "badges": {
                name: mark_safe(machine_translated_badge()) if was else ""
                for name, (_text, was) in shown[entry.pk].items()
            },
        }
        for entry in found
    ]
    response = render(
        request,
        "frontend/logbook/list.html",
        {
            "page_title": _("Logbook"),
            "entries": entries,
            "searching": bool(q),
            "searchable": True,
            "search_query": q,
            "search_placeholder": _("Search logbook"),
            "filters": [],
        },
    )
    add_never_cache_headers(response)
    return response


def _editable_entry(request, pk):
    entry = get_object_or_404(LogEntry, pk=pk)
    if not logbook.can_edit(request.user, entry):
        raise Http404
    return entry


def _form_page(request, form, title):
    response = render(
        request,
        "frontend/logbook/form.html",
        {"page_title": title, "back_url": reverse("logbook-list"), "form": form},
    )
    add_never_cache_headers(response)
    return response


def logbook_new(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    form = LogEntryForm(request.POST or None, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.author = request.user
        entry.save()
        logbook.queue_translation(entry)
        return redirect(f"{reverse('logbook-list')}#entry-{entry.pk}")
    return _form_page(request, form, _("New entry"))


def logbook_edit(request, pk):
    """The form starts from the text as the reader sees it - the machine translation, when they
    read one - so an entry can be corrected in either language. Saving makes the submitted text the
    entry's original (the previous original is overwritten) and queues its translation into the
    other language."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    entry = _editable_entry(request, pk)
    shown = logbook.display([entry])[entry.pk]
    initial = {name: text for name, (text, _translated) in shown.items()}
    form = LogEntryForm(request.POST or None, instance=entry, initial=initial)
    if request.method == "POST" and form.is_valid():
        if form.has_changed():
            form.save()
            logbook.queue_translation(entry)
        return redirect(f"{reverse('logbook-list')}#entry-{entry.pk}")
    return _form_page(request, form, _("Edit entry"))


@require_POST
def logbook_delete(request, pk):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    _editable_entry(request, pk).delete()
    return redirect("logbook-list")
