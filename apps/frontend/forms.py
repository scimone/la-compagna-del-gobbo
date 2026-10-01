from django import forms
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
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


class _LogEntryForm(forms.ModelForm):
    """The Logbook's add/edit forms. The date is pre-filled with today by the view (a new entry's
    `initial`), not hard-wired here, so editing an old entry shows its own date."""

    class Meta:
        model = LogEntry
        fields = ["date", "title", "text"]
        labels = {"date": _("Date"), "title": _("Title"), "text": _("Entry")}
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "text": forms.Textarea(attrs={"rows": 8}),
        }


class ObjectiveEntryForm(_LogEntryForm):
    """What happened at a session: a date, a title and the text."""

    class Meta(_LogEntryForm.Meta):
        fields = ["date", "title", "text"]


class PersonalEntryForm(_LogEntryForm):
    """A character's own, subjective words: a date, who writes, and the text."""

    class Meta(_LogEntryForm.Meta):
        fields = ["date", "character", "text"]
        labels = {**_LogEntryForm.Meta.labels, "character": _("Character")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields["character"]
        field.required = True
        field.empty_label = "---------"
        field.queryset = Character.objects.filter(status=Character.STATUS_COMPLETE).order_by(
            "name", "pk"
        )
