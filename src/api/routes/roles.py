"""Role management routes — list and get role details."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.schemas import RoleCreateRequest, RoleDetailResponse, RoleListResponse, RoleUpdateRequest
from src.roles.loader import Role, RoleError

router = APIRouter(prefix="/roles", tags=["roles"])


def _get_role_loader():
    from src.api.server import get_app_state
    return get_app_state().engine.role_loader


def _role_to_summary(role: Role) -> dict:
    return {
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
        "icon": role.icon,
        "personality": role.personality,
        "greeting": role.greeting,
        "signoff": role.signoff,
        "status_text": role.status_text,
        "tone": role.tone,
        "idle_style": role.idle_style,
        "busy_style": role.busy_style,
        "success_style": role.success_style,
        "failure_style": role.failure_style,
        "handoff_style": role.handoff_style,
    }


def _role_to_detail(role: Role) -> dict:
    return {
        "name": role.name,
        "display_name": role.display_name,
        "description": role.description,
        "icon": role.icon,
        "system_prompt": role.system_prompt,
        "tools": role.tools_override,
        "model": role.model,
        "personality": role.personality,
        "greeting": role.greeting,
        "signoff": role.signoff,
        "status_text": role.status_text,
        "tone": role.tone,
        "idle_style": role.idle_style,
        "busy_style": role.busy_style,
        "success_style": role.success_style,
        "failure_style": role.failure_style,
        "handoff_style": role.handoff_style,
    }


@router.get("", response_model=RoleListResponse)
def list_roles():
    """List all available roles."""
    loader = _get_role_loader()
    roles = loader.list_roles()
    return {"roles": [_role_to_summary(r) for r in roles]}


@router.get("/{name}", response_model=RoleDetailResponse)
def get_role(name: str):
    """Get a specific role's full details."""
    loader = _get_role_loader()
    role = loader.get(name)
    if role is None:
        raise HTTPException(status_code=404, detail=f"Role '{name}' not found")
    return {"role": _role_to_detail(role)}


@router.post("", response_model=RoleDetailResponse, status_code=201)
def create_role(body: RoleCreateRequest):
    """Create a new role."""
    loader = _get_role_loader()
    try:
        role = loader.save_role(
            name=body.name,
            display_name=body.display_name,
            description=body.description,
            system_prompt=body.system_prompt,
            icon=body.icon,
            tools_override=body.tools,
            model=body.model,
            personality=body.personality,
            greeting=body.greeting,
            signoff=body.signoff,
            status_text=body.status_text,
            tone=body.tone,
            idle_style=body.idle_style,
            busy_style=body.busy_style,
            success_style=body.success_style,
            failure_style=body.failure_style,
            handoff_style=body.handoff_style,
        )
    except RoleError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"role": _role_to_detail(role)}


@router.put("/{name}", response_model=RoleDetailResponse)
def update_role(name: str, body: RoleUpdateRequest):
    """Update an existing role."""
    loader = _get_role_loader()
    existing = loader.get(name)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Role '{name}' not found")

    # Build updated fields from non-None values
    updates = body.model_dump(exclude_unset=True)
    target_name = updates.pop("name", None) or name

    # Check for name collision if renaming
    if target_name != name and loader.get(target_name) is not None:
        raise HTTPException(status_code=409, detail=f"Role '{target_name}' already exists")

    try:
        role = loader.save_role(
            name=target_name,
            display_name=updates.get("display_name", existing.display_name),
            description=updates.get("description", existing.description),
            system_prompt=updates.get("system_prompt", existing.system_prompt),
            icon=updates.get("icon", existing.icon),
            tools_override=updates.get("tools", existing.tools_override),
            model=updates.get("model", existing.model),
            personality=updates.get("personality", existing.personality),
            greeting=updates.get("greeting", existing.greeting),
            signoff=updates.get("signoff", existing.signoff),
            status_text=updates.get("status_text", existing.status_text),
            tone=updates.get("tone", existing.tone),
            idle_style=updates.get("idle_style", existing.idle_style),
            busy_style=updates.get("busy_style", existing.busy_style),
            success_style=updates.get("success_style", existing.success_style),
            failure_style=updates.get("failure_style", existing.failure_style),
            handoff_style=updates.get("handoff_style", existing.handoff_style),
        )
    except RoleError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # If name changed, remove the old entry from cache
    if target_name != name:
        loader.delete_role(name)

    return {"role": _role_to_detail(role)}


@router.delete("/{name}")
def delete_role(name: str):
    """Delete a role. Cannot delete the default role."""
    loader = _get_role_loader()
    try:
        success = loader.delete_role(name)
    except RoleError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not success:
        raise HTTPException(status_code=404, detail=f"Role '{name}' not found")
    return {"ok": True}
