from django import forms
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _


class SignInForm(forms.Form):
    username = forms.CharField(
        label=_("Name"),
        max_length=150,
        validators=[AbstractUser.username_validator],
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autocapitalize": "none", "autofocus": True}
        ),
    )
