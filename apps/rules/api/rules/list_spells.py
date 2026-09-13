from typing import Annotated

from ninja import Query

from apps.rules.api.rules import router
from apps.rules.schemas import SpellSchema
from apps.rules.services import spell


@router.get("/spells", response=list[SpellSchema])
def list_spells(
    request,
    klass: Annotated[str | None, Query(alias="class")] = None,
    level: int | None = None,
):
    return spell.list_spells(klass=klass, level=level)
