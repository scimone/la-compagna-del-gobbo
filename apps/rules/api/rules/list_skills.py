from apps.rules.api.rules import router
from apps.rules.schemas import SkillSchema
from apps.rules.services import skill


@router.get("/skills", response=list[SkillSchema])
def list_skills(request):
    return skill.list_skills()
