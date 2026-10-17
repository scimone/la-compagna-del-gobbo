"""The campaign the signed-in person is looking at (Characters and Logbook show only its
content). It is remembered in the session; if it is gone or no longer theirs, the first campaign
they joined takes its place."""

from apps.campaigns.services import invites, membership


def current(request):
    """The current `Campaign`, or `None` for someone in no campaign (or signed out). Resolved once
    per request."""
    if not hasattr(request, "_current_campaign"):
        user = getattr(request, "user", None)
        campaign = None
        if user is not None and user.is_authenticated:
            session = request.session
            campaign = membership.resolve_current(user, session.get(membership.SESSION_KEY))
            wanted = campaign.pk if campaign else None
            if session.get(membership.SESSION_KEY) != wanted:
                if wanted is None:
                    session.pop(membership.SESSION_KEY, None)
                else:
                    session[membership.SESSION_KEY] = wanted
        request._current_campaign = campaign
    return request._current_campaign


def switch(request, campaign) -> None:
    request.session[membership.SESSION_KEY] = campaign.pk
    request._current_campaign = campaign


def context(request):
    """Template context: the current campaign and how many invitations wait for the user. Both
    are callables, so pages that never mention them (the World, the Handbook) pay no queries."""

    def pending() -> int:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return 0
        return invites.pending_for(user).count()

    def campaign():
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not hasattr(request, "session"):
            return None
        return current(request)

    return {"current_campaign": campaign, "pending_invite_count": pending}
