"""The Logbook menu: the party's shared journal, a vertical timeline of session entries."""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.frontend import logbook, logbook_markup
from apps.frontend.forms import ObjectiveEntryForm, PersonalEntryForm
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
            "personal": entry.kind == LogEntry.PERSONAL,
            "avatar": logbook.avatar_url(entry),
            "fields": {
                name: logbook_markup.render(text, pattern) if name == "text" else mark(text)
                for name, (text, _t) in shown[entry.pk].items()
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
        {
            "page_title": title,
            "back_url": reverse("logbook-list"),
            "form": form,
            "text_html": logbook_markup.render(form["text"].value() or ""),
        },
    )
    add_never_cache_headers(response)
    return response


def _form_class(kind):
    return PersonalEntryForm if kind == LogEntry.PERSONAL else ObjectiveEntryForm


def logbook_new(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    kind = request.GET.get("kind")
    kind = LogEntry.PERSONAL if kind == LogEntry.PERSONAL else LogEntry.OBJECTIVE
    initial = {"date": timezone.localdate()}
    form = _form_class(kind)(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.kind = kind
        entry.author = request.user
        entry.save()
        logbook.queue_translation(entry)
        return redirect(f"{reverse('logbook-list')}#entry-{entry.pk}")
    title = _("New entry") if kind == LogEntry.OBJECTIVE else _("New personal message")
    return _form_page(request, form, title)


def logbook_edit(request, pk):
    """The form starts from the text as the reader sees it - the machine translation, when they
    read one - so an entry can be corrected in either language. Saving makes the submitted text the
    entry's original (the previous original is overwritten) and queues its translation into the
    other language."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    entry = _editable_entry(request, pk)
    shown = logbook.display([entry])[entry.pk]
    form_class = _form_class(entry.kind)
    initial = {
        name: text for name, (text, _translated) in shown.items() if name in form_class._meta.fields
    }
    form = form_class(request.POST or None, instance=entry, initial=initial, user=request.user)
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


@require_POST
def logbook_preview(request):
    """The editor's way from Markdown back to its visual box: the text, rendered."""
    if not request.user.is_authenticated:
        raise Http404
    return HttpResponse(logbook_markup.render(request.POST.get("text", "")[:20000]))
