"""The Logbook menu: the party's shared journal, a vertical timeline of session entries."""

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import add_never_cache_headers
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.campaigns.services import membership
from apps.frontend import campaign_context, campaign_views, logbook, logbook_markup
from apps.frontend.forms import ObjectiveEntryForm, PersonalEntryForm
from apps.frontend.handbook_search import highlight, query_pattern
from apps.frontend.models import LogEntry, LogEntryImage


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


def _campaign_or_none(request):
    """The current campaign, if the user is in one; the Logbook shows only that one's entries."""
    campaign = campaign_context.current(request)
    return campaign if campaign and membership.is_member(request.user, campaign) else None


def logbook_list(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _campaign_or_none(request)
    if campaign is None:
        return campaign_views.no_campaign_page(request, _("Logbook"))
    q = request.GET.get("q", "").strip()
    found = list(logbook.list_entries(campaign))
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
            "dm": entry.as_dm,
            "avatar": logbook.avatar_url(entry),
            "full": logbook.full_url(entry),
            "banner": logbook.banner_url(entry),
            "banner_style": logbook.banner_style(entry),
            "images": [reverse("logbook-image", args=[i.pk]) for i in entry.images.all()],
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
    entry = get_object_or_404(LogEntry.objects.select_related("campaign"), pk=pk)
    if not logbook.can_edit(request.user, entry):
        raise Http404
    return entry


def _uploads(request, form, already=0):
    """The banner and pictures chosen in the form, encoded; a bad one becomes a form error (None
    then)."""
    try:
        return {
            "images": logbook.encode_images(request.FILES.getlist("images"), already),
            "banner": logbook.encode_banner(request.FILES.get("banner")),
        }
    except ValueError as error:
        form.add_error(None, str(error))
        return None


def _save_frame(request, entry):
    """Store the banner's frame as the editor left it (a new banner starts centred)."""
    if entry.banner and "banner_x" in request.POST:
        post = request.POST
        logbook.set_banner_frame(
            entry, post.get("banner_x"), post.get("banner_y"), post.get("banner_zoom")
        )


def _form_page(request, form, title, entry=None):
    response = render(
        request,
        "frontend/logbook/form.html",
        {
            "images": entry.images.all() if entry else [],
            "banner": logbook.banner_url(entry) if entry else "",
            "banner_style": logbook.banner_style(entry) if entry else "",
            "frame": entry,
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
    campaign = _campaign_or_none(request)
    if campaign is None:
        raise Http404
    initial = {"date": timezone.localdate()}
    form = _form_class(kind)(
        request.POST or None, initial=initial, user=request.user, campaign=campaign
    )
    if (
        request.method == "POST"
        and form.is_valid()
        and (pictures := _uploads(request, form)) is not None
    ):
        entry = form.save(commit=False)
        entry.kind = kind
        entry.author = request.user
        entry.campaign = campaign
        entry.save()
        logbook.add_images(entry, pictures["images"])
        logbook.set_banner(entry, pictures["banner"])
        _save_frame(request, entry)
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
    form = form_class(
        request.POST or None,
        instance=entry,
        initial=initial,
        user=request.user,
        campaign=entry.campaign,
    )
    if request.method == "POST" and form.is_valid():
        removed = [int(i) for i in request.POST.getlist("remove_image") if i.isdigit()]
        kept = entry.images.exclude(pk__in=removed).count()
        pictures = _uploads(request, form, kept)
        if pictures is not None:
            if form.has_changed():
                form.save()
                logbook.queue_translation(entry)
            logbook.remove_images(entry, removed)
            logbook.add_images(entry, pictures["images"])
            logbook.set_banner(
                entry, pictures["banner"], remove=bool(request.POST.get("remove_banner"))
            )
            _save_frame(request, entry)
            return redirect(f"{reverse('logbook-list')}#entry-{entry.pk}")
    return _form_page(request, form, _("Edit entry"), entry)


def logbook_banner(request, pk):
    """An entry's banner, for members of its campaign."""
    entry = get_object_or_404(LogEntry.objects.select_related("campaign"), pk=pk)
    if not entry.banner or not request.user.is_authenticated:
        raise Http404
    if not membership.is_member(request.user, entry.campaign):
        raise Http404
    try:
        with entry.banner.open("rb") as file:
            data = file.read()
    except FileNotFoundError:
        raise Http404 from None
    response = HttpResponse(data, content_type="image/webp")
    response["Cache-Control"] = "private, max-age=86400"
    return response


def logbook_image(request, pk):
    """One attached picture, for members of the entry's campaign."""
    image = get_object_or_404(LogEntryImage.objects.select_related("entry__campaign"), pk=pk)
    if not request.user.is_authenticated or not membership.is_member(
        request.user, image.entry.campaign
    ):
        raise Http404
    try:
        with image.image.open("rb") as file:
            data = file.read()
    except FileNotFoundError:
        raise Http404 from None
    response = HttpResponse(data, content_type="image/webp")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@require_POST
def logbook_delete(request, pk):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    logbook.delete_entry(_editable_entry(request, pk))
    return redirect("logbook-list")


@require_POST
def logbook_preview(request):
    """The editor's way from Markdown back to its visual box: the text, rendered."""
    if not request.user.is_authenticated:
        raise Http404
    return HttpResponse(logbook_markup.render(request.POST.get("text", "")[:20000]))
