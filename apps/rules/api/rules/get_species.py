from apps.rules.api.rules import router
from apps.rules.schemas import SpeciesSchema
from apps.rules.services import species


@router.get("/species/{species_id}", response=SpeciesSchema)
def get_species(request, species_id: str):
    return species.get_species(species_id)
