from apps.rules.api.rules import router
from apps.rules.schemas import SpeciesSchema
from apps.rules.services import species


@router.get("/species", response=list[SpeciesSchema])
def list_species(request):
    return species.list_species()
