"""Clause template library endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.models.contract import ClauseType
from src.services.template_library import ClauseTemplate

router = APIRouter()


class CreateTemplateRequest(BaseModel):
    clause_type: ClauseType
    name: str
    text: str
    description: str = ""
    tags: list[str] = []
    created_by: str = ""


@router.post("/", response_model=dict)
async def create_template(req: CreateTemplateRequest, request: Request):
    templates = request.app.state.templates
    template = ClauseTemplate(
        clause_type=req.clause_type,
        name=req.name,
        text=req.text,
        description=req.description,
        tags=req.tags,
        created_by=req.created_by,
    )
    templates.save_template(template)
    return {"id": template.id, "name": template.name}


@router.get("/")
async def list_templates(
    request: Request,
    clause_type: ClauseType | None = None,
):
    templates = request.app.state.templates
    results = templates.get_templates(clause_type)
    return [
        {
            "id": t.id,
            "clause_type": t.clause_type.value,
            "name": t.name,
            "text": t.text,
            "description": t.description,
            "tags": t.tags,
            "is_default": t.is_default,
            "created_by": t.created_by,
        }
        for t in results
    ]


@router.get("/{template_id}")
async def get_template(template_id: str, request: Request):
    templates = request.app.state.templates
    t = templates.get_template(template_id)
    return {
        "id": t.id,
        "clause_type": t.clause_type.value,
        "name": t.name,
        "text": t.text,
        "description": t.description,
        "tags": t.tags,
        "is_default": t.is_default,
        "created_by": t.created_by,
    }


@router.delete("/{template_id}")
async def delete_template(template_id: str, request: Request):
    templates = request.app.state.templates
    templates.delete_template(template_id)
    return {"deleted": template_id}
