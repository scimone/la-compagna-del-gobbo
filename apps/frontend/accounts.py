"""Password-less accounts: typing a name signs you in as that account, creating it if new.

This is identity without authentication - anyone who types someone else's name gets that
person's bookmarks. It exists so a small group of friends each has their own bookmarks, not to
protect anything. Accounts are plain `auth.User` rows with an *unusable* password, so adding real
password auth later needs no schema change (`set_password()` on the account, then a password
field on the form).

Sign-in by name alone is therefore refused for any account that has a usable password (a
superuser made with `createsuperuser`, say) - otherwise typing "admin" would be a way in.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError


def display_name(user) -> str:
    """What to call `user` on screen: the name they gave on first sign-in, else the username."""
    return (user.first_name or "").strip() or user.get_username()


def get_or_create_passwordless_user(username: str):
    """The account called `username` (case-insensitive), created if it doesn't exist yet - or
    `None` if it exists but is a real, password-protected account.
    """
    User = get_user_model()
    user = User.objects.filter(username__iexact=username).first()
    if user is None:
        try:
            user = User.objects.create_user(username=username)  # no password -> unusable
        except IntegrityError:  # someone else just created it
            user = User.objects.get(username__iexact=username)
    return user if not user.has_usable_password() else None
