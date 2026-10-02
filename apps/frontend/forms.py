from django import forms
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _

from apps.characters.models import Character
from apps.characters.services import access
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user


class ObjectiveEntryForm(_LogEntryForm):
    """What happened at a session: a date, a title and the text."""

    class Meta(_LogEntryForm.Meta):
        fields = ["date", "title", "text"]


class PersonalEntryForm(_LogEntryForm):
    """A character's own, subjective words: a date, who writes, and the text.

    A character writes from its own perspective, so only an administrator picks who writes (from
    every finished character). A player writes as their own character: with one, there is nothing
    to choose; with several, the choice is among theirs; with none, nothing can be saved."""

    class Meta(_LogEntryForm.Meta):
        fields = ["date", "character", "text"]
        labels = {**_LogEntryForm.Meta.labels, "character": _("Character")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        characters = Character.objects.filter(status=Character.STATUS_COMPLETE).order_by(
            "name", "pk"
        )
        if not access.is_admin(self.user):
            characters = characters.filter(owner=self.user)
        field = self.fields["character"]
        field.required = True
        field.empty_label = "---------"
        field.queryset = characters
        self.only = None
        self.dm_option = access.can_speak_as_dm(self.user)
        if self.dm_option:
            # The extra option "DM" is the empty choice: no character speaks, the DM does.
            field.required = False
            field.empty_label = _("DM")
            if self.instance.pk and self.instance.as_dm:
                self.initial["character"] = None
        if not self.dm_option and not access.is_admin(self.user) and characters.count() <= 1:
            # Nothing to choose: the (only) character writes.
            self.only = self.instance.character or characters.first()
            del self.fields["character"]
        elif not self.instance.pk and (own := characters.filter(owner=self.user).first()):
            self.initial.setdefault("character", own.pk)

    def clean(self):
        cleaned = super().clean()
        if self.dm_option and "character" in self.fields and not cleaned.get("character"):
            if "character" not in self.errors:
                self.instance.as_dm = True
            return cleaned
        self.instance.as_dm = False
        if "character" not in self.fields:
            if self.only is None:
                raise forms.ValidationError(
                    _("You need a finished character to write a personal message.")
                )
            self.instance.character = self.only
        return cleaned
