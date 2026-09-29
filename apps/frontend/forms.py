from django import forms
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

from apps.frontend.models import LogEntry


class SignInForm(forms.Form):
    username = forms.CharField(
        label=_("Name"),
        max_length=150,
        validators=[AbstractUser.username_validator],
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "autofocus": True}
        ),
    )


class NameForm(forms.Form):
    """Asked once, after the first Google sign-in: what the person wants to be called."""

    name = forms.CharField(
        label=_("Your name"),
        max_length=150,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "given-name", "autofocus": True}),
    )


class LogEntryForm(forms.ModelForm):
    """The Logbook's add/edit form. The date is pre-filled with today by the view (a new entry's
    `initial`), not hard-wired here, so editing an old entry shows its own date."""

    class Meta:
        model = LogEntry
        fields = [
            "date",
            "title",
            "location",
            "characters_met",
            "fights",
            "objectives",
            "insights",
            "notes",
        ]
        labels = {
            "date": _("Date"),
            "title": _("Title"),
            "location": _("Visited locations"),
            "characters_met": _("Characters met"),
            "fights": _("Fights"),
            "objectives": _("Objectives"),
            "insights": _("Insights"),
            "notes": _("Other notes"),
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "location": forms.Textarea(attrs={"rows": 3}),
            "characters_met": forms.Textarea(attrs={"rows": 3}),
            "fights": forms.Textarea(attrs={"rows": 3}),
            "objectives": forms.Textarea(attrs={"rows": 3}),
            "insights": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
