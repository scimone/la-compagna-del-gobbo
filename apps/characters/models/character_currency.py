from django.db import models


class CharacterCurrency(models.Model):
    """The coin purse of a Character - the five standard denominations (copper/silver/electrum/
    gold/platinum).

    A true 1:1 with `Character` (a character has exactly one purse), so `character` is both the
    FK and the primary key rather than a separate auto id - the standard Django pattern for a
    "detail" table.
    """

    character = models.OneToOneField(
        "characters.Character",
        related_name="currency",
        on_delete=models.CASCADE,
        primary_key=True,
    )
    copper = models.PositiveIntegerField(default=0)
    silver = models.PositiveIntegerField(default=0)
    electrum = models.PositiveIntegerField(default=0)
    gold = models.PositiveIntegerField(default=0)
    platinum = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return f"{self.character}'s purse"
