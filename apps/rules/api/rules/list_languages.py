from apps.rules.api.rules import router
from apps.rules.schemas import LanguageSchema
from apps.rules.services import language


@router.get("/languages", response=list[LanguageSchema])
def list_languages(request):
    return language.list_languages()
