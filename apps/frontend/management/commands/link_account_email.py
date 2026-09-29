from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Attach a Google e-mail to an existing account, so signing in through Cloudflare Access "
        "as that address lands on it (with its characters and bookmarks) instead of a new one."
    )

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("email")

    def handle(self, *args, username, email, **options):
        User = get_user_model()
        email = email.strip().lower()
        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            raise CommandError(f"No account called {username!r}.")
        clash = User.objects.filter(email__iexact=email).exclude(pk=user.pk).first()
        if clash is not None:
            raise CommandError(
                f"{email} already belongs to {clash.get_username()!r} - merge or clear that first."
            )
        user.email = email
        user.save(update_fields=["email"])
        self.stdout.write(f"{user.get_username()} is now linked to {email}.")
