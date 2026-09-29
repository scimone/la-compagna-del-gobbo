from django.db import models


class CharacterPicture(models.Model):
    """A picture in a character's gallery (Biography tab), besides the single `portrait`.

    Stored like the portrait: re-encoded by `characters.services.portrait` before it is saved.
    """

    character = models.ForeignKey(
        "characters.Character", related_name="pictures", on_delete=models.CASCADE
    )
    image = models.ImageField(upload_to="gallery/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.character}: {self.image.name}"
