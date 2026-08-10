"""Skill management routes."""

from fastapi import APIRouter

from src.core.engine import WorkPartnerEngine

router = APIRouter(prefix="/skills", tags=["skills"])


def get_engine() -> WorkPartnerEngine:
    from src.api.server import get_app_state
    return get_app_state().engine


@router.get("")
def list_skills():
    """List all loaded skills."""
    engine = get_engine()
    skills = []
    for s in engine.skill_loader.list_all():
        skills.append({
            "name": s.name,
            "description": s.description,
            "version": s.version,
            "should_auto_load": s.should_auto_load,
            "path": f"skills/{s.name}/SKILL.md",
        })
    return {"skills": skills}


@router.post("/refresh")
def refresh_skills():
    """Re-scan skills directory and reload all skills."""
    engine = get_engine()
    old_names = set(engine.skill_loader.list_names())
    engine.skill_loader.load_all()
    new_names = set(engine.skill_loader.list_names())

    # Also reset the injector's loaded-skill tracking so newly added skills
    # can be picked up on the next turn
    engine.skill_injector.reset_session()

    return {
        "count": len(new_names),
        "added": sorted(new_names - old_names),
        "removed": sorted(old_names - new_names),
        "skills": [
            {
                "name": s.name,
                "description": s.description,
                "version": s.version,
                "should_auto_load": s.should_auto_load,
            }
            for s in engine.skill_loader.list_all()
        ],
    }
