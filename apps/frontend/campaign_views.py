"""Campaign pages: the list (and the invitations waiting), creating and joining, one campaign's
members, invitations and join link, and the character copy/transfer picker.

All rules live in `apps.campaigns.services` and `apps.characters.services.campaign_ops`; these
views only ask who may and show the result. Someone who is not in a campaign gets a 404 for it.
"""

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.campaigns.models import Campaign, CampaignInvite, CampaignMembership
from apps.campaigns.services import invites, lifecycle, membership
from apps.characters.models import Character
from apps.characters.services import access, campaign_ops
from apps.frontend import accounts, campaign_context


def _sign_in_redirect(request):
    return redirect(f"{reverse('account')}?next={request.get_full_path()}")


def _page(request, template, context):
    response = render(request, template, context)
    add_never_cache_headers(response)
    return response


def _own_campaign(request, pk):
    """The campaign `pk` if the user may open it, else a 404."""
    return get_object_or_404(membership.campaigns_for(request.user), pk=pk)


def _fail(request, error: ValueError) -> None:
    messages.error(request, str(error))


def no_campaign_page(request, title):
    """Characters and the Logbook of someone who is in no campaign yet: how to get into one."""
    return _page(request, "frontend/campaigns/none.html", {"page_title": title, "back_url": None})


# --- the list ---------------------------------------------------------------------------------


def campaigns_home(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    current = campaign_context.current(request)
    rows = []
    for campaign in membership.campaigns_for(request.user).prefetch_related("memberships"):
        role = membership.role_in(request.user, campaign)
        rows.append(
            {
                "campaign": campaign,
                "role": role,
                "role_label": _("DM") if role == CampaignMembership.DM else _("Player"),
                "members": campaign.memberships.count(),
                "current": current is not None and campaign.pk == current.pk,
            }
        )
    return _page(
        request,
        "frontend/campaigns/list.html",
        {
            "page_title": _("Campaigns"),
            "back_url": reverse("account"),
            "rows": rows,
            "invites": invites.pending_for(request.user),
            "is_admin": access.is_admin(request.user),
        },
    )


def campaign_new(request):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    if request.method == "POST":
        try:
            campaign = lifecycle.create_campaign(
                request.user, request.POST.get("name", ""), request.POST.get("description", "")
            )
        except ValueError as error:
            _fail(request, error)
        else:
            campaign_context.switch(request, campaign)
            return redirect("campaign-detail", pk=campaign.pk)
    return _page(
        request,
        "frontend/campaigns/new.html",
        {
            "page_title": _("New campaign"),
            "back_url": reverse("campaigns-home"),
            "name": request.POST.get("name", ""),
            "description": request.POST.get("description", ""),
        },
    )


@require_POST
def campaign_switch(request, pk):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _own_campaign(request, pk)
    campaign_context.switch(request, campaign)
    target = request.POST.get("next", "")
    if not target or not url_has_allowed_host_and_scheme(target, allowed_hosts=None):
        target = reverse("characters-overview")
    return redirect(target)


# --- invitations & the join link ---------------------------------------------------------------


@require_POST
def invite_answer(request, pk, answer):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    invite = get_object_or_404(invites.pending_for(request.user), pk=pk)
    try:
        if answer == "accept":
            invites.accept(invite, request.user)
            campaign_context.switch(request, invite.campaign)
            return redirect("characters-overview")
        if answer == "decline":
            invites.decline(invite, request.user)
        else:
            raise Http404
    except ValueError as error:
        _fail(request, error)
    return redirect("campaigns-home")


def _code_from(text: str) -> str:
    """The code in what the user typed: the bare code, or the whole join link."""
    return text.strip().rstrip("/").rsplit("/", 1)[-1]


@require_POST
def campaign_join_form(request):
    """The "I have a code" box on the campaigns page."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    code = _code_from(request.POST.get("code", ""))
    return redirect("campaign-join", code=code) if code else redirect("campaigns-home")


def campaign_join(request, code):
    """A join link: asks for confirmation, then makes the visitor a player of the campaign."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = Campaign.objects.filter(join_code=code, join_enabled=True).first()
    if campaign is None:
        return _page(
            request,
            "frontend/campaigns/join.html",
            {"page_title": _("Join a campaign"), "back_url": reverse("campaigns-home")},
        )
    if request.method == "POST":
        try:
            lifecycle.join_via_code(request.user, code)
        except ValueError as error:
            _fail(request, error)
        else:
            campaign_context.switch(request, campaign)
            return redirect("characters-overview")
    return _page(
        request,
        "frontend/campaigns/join.html",
        {
            "page_title": _("Join a campaign"),
            "back_url": reverse("campaigns-home"),
            "campaign": campaign,
            "already": membership.is_member(request.user, campaign),
        },
    )


# --- one campaign ------------------------------------------------------------------------------


def _leave_warning(campaign, user) -> str:
    lost = campaign_ops.characters_lost_on_leaving(campaign, user)
    if not lost:
        return _("Leave this campaign?")
    names = ", ".join(c.name for c in lost)
    return _(
        "Leaving deletes your characters in this campaign, for good: %(names)s. Leave anyway?"
    ) % {"names": names}


def campaign_detail(request, pk):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _own_campaign(request, pk)
    me = membership.membership_of(request.user, campaign)
    can_manage = membership.can_manage(request.user, campaign)
    rows = membership.members(campaign)
    people = [
        {
            "membership": m,
            "name": accounts.display_name(m.user),
            "is_dm": m.role == CampaignMembership.DM,
            "is_me": m.user_id == request.user.id,
            "characters": Character.objects.filter(campaign=campaign, owner=m.user).count(),
            "remove_warning": (
                _("Remove %(name)s? Their characters in this campaign are deleted, for good.")
                % {"name": accounts.display_name(m.user)}
            ),
        }
        for m in rows
    ]
    return _page(
        request,
        "frontend/campaigns/detail.html",
        {
            "page_title": campaign.name,
            "back_url": reverse("campaigns-home"),
            "campaign": campaign,
            "people": people,
            "can_manage": can_manage,
            "member": me is not None,
            "is_dm": me is not None and me.role == CampaignMembership.DM,
            "open_invites": invites.open_invites(campaign),
            "join_url": request.build_absolute_uri(
                reverse("campaign-join", args=[campaign.join_code])
            ),
            "leave_warning": _leave_warning(campaign, request.user) if me else "",
            "has_characters": campaign.characters.exists(),
        },
    )


def _target_member(campaign, post):
    """The membership named by the form's `user` field, or `None`."""
    try:
        user_id = int(post.get("user", ""))
    except ValueError:
        return None
    return CampaignMembership.objects.filter(campaign=campaign, user_id=user_id).first()


def _act_rename(request, campaign):
    lifecycle.update_campaign(
        campaign, request.POST.get("name", ""), request.POST.get("description", "")
    )
    messages.success(request, _("Saved."))


def _act_invite(request, campaign):
    invite = invites.invite(campaign, request.user, request.POST.get("email", ""))
    messages.success(request, _("Invitation sent to %(email)s.") % {"email": invite.email})


def _act_revoke_invite(request, campaign):
    invite = get_object_or_404(CampaignInvite, pk=request.POST.get("invite"), campaign=campaign)
    if invite.invited_by_id != request.user.id and not membership.can_manage(
        request.user, campaign
    ):
        raise Http404
    invites.revoke(invite)


def _act_regenerate_code(request, campaign):
    lifecycle.regenerate_join_code(campaign)
    messages.success(request, _("The old join link no longer works."))


def _act_join_enabled(request, campaign):
    lifecycle.set_join_enabled(campaign, request.POST.get("enabled") == "1")


def _act_transfer_dm(request, campaign):
    target = _target_member(campaign, request.POST)
    if target is None:
        raise ValueError(_("Pick a member."))
    lifecycle.transfer_dm(campaign, target.user)
    messages.success(
        request,
        _("%(name)s is now the DM.") % {"name": accounts.display_name(target.user)},
    )


def _act_remove_member(request, campaign):
    target = _target_member(campaign, request.POST)
    if target is None:
        raise ValueError(_("Pick a member."))
    campaign_ops.remove_member(campaign, target.user)


def _act_delete(request, campaign):
    campaign_ops.delete_campaign(campaign)


#: action -> (handler, who may). "member": any member; "manage": the DM or an admin.
_ACTIONS = {
    "rename": (_act_rename, "manage"),
    "invite": (_act_invite, "member"),
    "revoke_invite": (_act_revoke_invite, "member"),
    "regenerate_code": (_act_regenerate_code, "manage"),
    "join_enabled": (_act_join_enabled, "manage"),
    "transfer_dm": (_act_transfer_dm, "manage"),
    "remove_member": (_act_remove_member, "manage"),
}


@require_POST
def campaign_act(request, pk):
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    campaign = _own_campaign(request, pk)
    action = request.POST.get("action", "")
    here = redirect("campaign-detail", pk=campaign.pk)
    try:
        if action == "leave":
            campaign_ops.remove_member(campaign, request.user)
            messages.success(request, _("You left %(name)s.") % {"name": campaign.name})
            return redirect("campaigns-home")
        if action == "delete":
            if not membership.can_manage(request.user, campaign):
                raise Http404
            _act_delete(request, campaign)
            return redirect("campaigns-home")
        handler, who = _ACTIONS.get(action, (None, None))
        if handler is None:
            raise Http404
        allowed = (
            membership.is_member(request.user, campaign)
            if who == "member"
            else membership.can_manage(request.user, campaign)
        )
        if not allowed:
            raise Http404
        handler(request, campaign)
    except ValueError as error:
        _fail(request, error)
    return here


# --- copy / move a character --------------------------------------------------------------------


def character_move(request, pk):
    """Pick a campaign to copy the character to (anyone who sees it) or move it to (its owner
    or DM). A copy belongs to whoever makes it."""
    if not request.user.is_authenticated:
        return _sign_in_redirect(request)
    character = get_object_or_404(Character.objects.select_related("campaign"), pk=pk)
    if character.status != Character.STATUS_COMPLETE or not access.can_view(
        request.user, character
    ):
        raise Http404
    mode = "transfer" if request.GET.get("mode") == "transfer" else "copy"
    if mode == "transfer" and not access.can_edit(request.user, character):
        raise Http404
    targets = list(membership.campaigns_for(request.user))
    if mode == "transfer":
        targets = [t for t in targets if t.pk != character.campaign_id]
    if request.method == "POST":
        target = next((t for t in targets if str(t.pk) == request.POST.get("campaign")), None)
        if target is None:
            messages.error(request, _("Pick a campaign."))
        else:
            try:
                if mode == "transfer":
                    campaign_ops.transfer_character(request.user, character, target)
                else:
                    character = campaign_ops.copy_character(request.user, character, target)
            except ValueError as error:
                _fail(request, error)
            else:
                campaign_context.switch(request, target)
                return redirect("character-detail", pk=character.pk)
    return _page(
        request,
        "frontend/campaigns/move.html",
        {
            "page_title": _("Move character") if mode == "transfer" else _("Copy character"),
            "back_url": reverse("character-detail", args=[character.pk]),
            "character": character,
            "mode": mode,
            "targets": targets,
        },
    )
