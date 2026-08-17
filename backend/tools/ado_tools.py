"""LangChain tools exposing Azure DevOps Work Item operations to the agent.

Each tool is a thin wrapper over :class:`backend.tools.ado_client.ADOClient`
that performs input validation (state allowlist, identity resolution, etc.)
and returns plain strings the LLM can use to compose a reply.

Tools provided:
    get_work_item
    search_work_items
    update_work_item
    create_work_item
    add_work_item_comment
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.tools.ado_client import ADOClient, ADOClientError

ALLOWED_WIT_TYPES = ("Bug", "Task", "User Story", "Issue", "Feature", "Epic")
DEFAULT_WIT_TYPES = ("Bug", "Task", "User Story")


# ----------------------------------------------------------------------------
# Field helpers
# ----------------------------------------------------------------------------

_FIELD_LABEL = {
    "System.Id": "id",
    "System.Title": "title",
    "System.State": "state",
    "System.WorkItemType": "type",
    "System.AssignedTo": "assigned_to",
    "System.CreatedBy": "created_by",
    "System.AreaPath": "area_path",
    "System.Tags": "tags",
    "System.Reason": "reason",
}


def _identity_name(value: Any) -> str:
    """Render an identity / list field as a short human-readable string.

    ADO returns ``System.AssignedTo`` as an IdentityRef dict; collapse it
    to ``displayName <uniqueName>`` so the LLM gets something readable.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        display = value.get("displayName", "")
        unique = value.get("uniqueName", "")
        return f"{display} <{unique}>" if unique else display
    return str(value)


def _render_work_item(wi: dict[str, Any]) -> str:
    """Format a single work-item JSON object as a compact text block."""
    fields = wi.get("fields", {})
    lines = []
    label_map = {
        "System.Id": "ID",
        "System.Title": "Title",
        "System.State": "State",
        "System.Reason": "Reason",
        "System.WorkItemType": "Type",
        "System.AssignedTo": "Assigned To",
        "System.CreatedBy": "Created By",
        "System.AreaPath": "Area",
        "System.Tags": "Tags",
        "System.IterationPath": "Iteration",
        "Microsoft.VSTS.Common.Priority": "Priority",
    }
    if "System.Id" not in fields and "id" in wi:
        # bring wi.id into fields for display
        fields = {"System.Id": wi.get("id"), **fields}
    for ref, label in label_map.items():
        if ref in fields:
            val = fields[ref]
            val = _identity_name(val) if ref in ("System.AssignedTo", "System.CreatedBy") else str(val)
            lines.append(f"  {label}: {val}")
    return "\n".join(lines) if lines else str(wi)


# ----------------------------------------------------------------------------
# Tool input schemas
# ----------------------------------------------------------------------------


class GetWorkItemArgs(BaseModel):
    work_item_id: int = Field(..., description="The integer ID of the Azure DevOps work item to retrieve.")


class SearchWorkItemsArgs(BaseModel):
    keywords: Optional[str] = Field(
        default=None,
        description=(
            "Free-text keywords to search for within work item titles and tags. "
            "If omitted, return recent open work items."
        ),
    )
    work_item_type: Optional[str] = Field(
        default=None,
        description=f"Restrict search to a work item type (e.g. {', '.join(DEFAULT_WIT_TYPES)}).",
    )
    state: Optional[str] = Field(
        default=None,
        description="Restrict to a state value (e.g. Active, New, Closed).",
    )
    top: int = Field(default=10, ge=1, le=100, description="Maximum number of results (1-100).")


class UpdateWorkItemArgs(BaseModel):
    work_item_id: int = Field(..., description="The integer ID of the work item to update.")
    title: Optional[str] = Field(default=None, description="New title. Leave null to keep existing.")
    state: Optional[str] = Field(
        default=None,
        description=(
            "New state value. Must be one of the project's allowed states for this "
            "work item type. The tool will validate it."
        ),
    )
    assigned_to: Optional[str] = Field(
        default=None,
        description=(
            "New assignee. Accepts a display name, an email/unique name, "
            'or "DisplayName<email>" form. Use empty string "" to unassign.'
        ),
    )
    comment: Optional[str] = Field(
        default=None, description="Add a discussion comment to the work item."
    )


class CreateWorkItemArgs(BaseModel):
    work_item_type: Literal["Bug", "Task", "User Story", "Issue", "Feature", "Epic"] = Field(
        ..., description="Type of work item to create."
    )
    title: str = Field(..., min_length=1, description="Title of the new work item.")
    description: str = Field(default="", description="Optional description (plain text).")
    area_path: Optional[str] = Field(
        default=None, description="Optional area path; defaults to the configured project area."
    )


class AddWorkItemCommentArgs(BaseModel):
    work_item_id: int = Field(..., description="The integer ID of the work item to comment on.")
    comment: str = Field(..., min_length=1, description="The comment text.")


# ----------------------------------------------------------------------------
# Tool implementations (functions -> StructuredTool)
# ----------------------------------------------------------------------------


async def _get_work_item(work_item_id: int) -> str:
    async with ADOClient() as client:
        wi = await client.get_work_item(work_item_id)
    return f"Work item #{work_item_id}:\n{_render_work_item(wi)}"


async def _search_work_items(
    keywords: Optional[str] = None,
    work_item_type: Optional[str] = None,
    state: Optional[str] = None,
    top: int = 10,
) -> str:
    clauses = ["[System.TeamProject] = '@project'"]
    if keywords:
        kw = keywords.replace("'", "''")
        clauses.append(f"([System.Title] CONTAINS '{kw}' OR [System.Tags] CONTAINS '{kw}')")
    if work_item_type:
        wit = work_item_type.replace("'", "''")
        clauses.append(f"[System.WorkItemType] = '{wit}'")
    if state:
        st = state.replace("'", "''")
        clauses.append(f"[System.State] = '{st}'")
    else:
        clauses.append("[System.State] <> 'Closed'")
        clauses.append("[System.State] <> 'Removed'")
    wiql = (
        "SELECT [System.Id], [System.Title], [System.State], [System.WorkItemType] "
        "FROM WorkItems WHERE "
        + " AND ".join(clauses)
        + " ORDER BY [System.ChangedDate] DESC"
    )
    async with ADOClient() as client:
        ids = await client.query_wiql(wiql, top=top)
        if not ids:
            return "No matching work items found."
        items = await client.get_work_items_batch(ids)
    if not items:
        return f"Found {len(ids)} matching work item(s) but could not retrieve their fields. IDs: {ids}"
    blocks = [_render_work_item(it) for it in items]
    return f"Found {len(items)} work item(s):\n\n" + "\n\n---\n\n".join(blocks)


async def _update_work_item(
    work_item_id: int,
    title: Optional[str] = None,
    state: Optional[str] = None,
    assigned_to: Optional[str] = None,
    comment: Optional[str] = None,
) -> str:
    """Update fields on a work item and optionally add a discussion comment.

    Validates ``state`` against the project's allowed-state list for the
    work item's type. Returns a summary of the final field snapshot.
    """
    async with ADOClient() as client:
        # Existing item needed to know its type, to validate the new state.
        existing = await client.get_work_item(work_item_id)
        fields = existing.get("fields", {})
        existing_type = fields.get("System.WorkItemType", "")

        patch_ops: list[dict[str, Any]] = []
        changes: list[str] = []
        if title is not None:
            patch_ops.append({"op": "add", "path": "/fields/System.Title", "value": title})
            changes.append(f"title → {title!r}")
        if state is not None:
            allowed = await client.get_work_item_type_states(existing_type)
            allowed_lower = {s.lower() for s in allowed}
            if allowed and state.lower() not in allowed_lower:
                return (
                    f"State {state!r} is not valid for a {existing_type}. "
                    f"Allowed: {', '.join(allowed)}"
                )
            patch_ops.append({"op": "add", "path": "/fields/System.State", "value": state})
            changes.append(f"state → {state!r}")
        if assigned_to is not None:
            patch_ops.append(
                {"op": "add", "path": "/fields/System.AssignedTo", "value": assigned_to}
            )
            changes.append(f"assigned_to → {assigned_to!r}")

        if patch_ops:
            await client.update_work_item(work_item_id, patch_ops)
        if comment:
            await client.add_work_item_comment(work_item_id, comment)
            changes.append(f"comment added ({len(comment)} chars)")

        if not changes:
            return "Nothing to update — no fields given."
        final = await client.get_work_item(work_item_id)

    summary = _render_work_item(final)
    return f"Updated work item #{work_item_id}. Changes: {', '.join(changes)}.\n\nNew state:\n{summary}"


async def _create_work_item(
    work_item_type: Literal["Bug", "Task", "User Story", "Issue", "Feature", "Epic"],
    title: str,
    description: str = "",
    area_path: Optional[str] = None,
) -> str:
    from backend.config import get_settings

    patch_ops: list[dict[str, Any]] = [
        {"op": "add", "path": "/fields/System.Title", "value": title},
    ]
    if description:
        patch_ops.append(
            {"op": "add", "path": "/fields/System.Description", "value": description}
        )
    settings = get_settings()
    resolved_area = area_path or settings.azure_devops_default_area
    if resolved_area:
        patch_ops.append(
            {"op": "add", "path": "/fields/System.AreaPath", "value": resolved_area}
        )

    async with ADOClient() as client:
        created = await client.create_work_item(work_item_type, patch_ops)

    new_id = created.get("id", "?")
    url = created.get("url", "")
    return f"Created {work_item_type} #{new_id} (title: {title!r}).\nURL: {url}"


async def _add_work_item_comment(work_item_id: int, comment: str) -> str:
    async with ADOClient() as client:
        result = await client.add_work_item_comment(work_item_id, comment)
    comment_id = result.get("commentId", "?")
    return f"Added comment #{comment_id} on work item #{work_item_id}."


# ----------------------------------------------------------------------------
# Public registry
# ----------------------------------------------------------------------------


def build_ado_tools() -> list[StructuredTool]:
    """Instantiate and return the ADO tool set used by the agent."""
    return [
        StructuredTool.from_function(
            _get_work_item,
            name="get_work_item",
            description=(
                "Get the full details of a single Azure DevOps work item given its "
                "integer ID. Returns id, title, state, type, assignee, and other fields."
            ),
            args_schema=GetWorkItemArgs,
        ),
        StructuredTool.from_function(
            _search_work_items,
            name="search_work_items",
            description=(
                "Search Azure DevOps work items by keywords, type, and/or state. "
                "Returns a summarized list. Use this before assuming an ID — never "
                "invent work item IDs, search first."
            ),
            args_schema=SearchWorkItemsArgs,
        ),
        StructuredTool.from_function(
            _update_work_item,
            name="update_work_item",
            description=(
                "Update one or more fields of an Azure DevOps work item: title, state, "
                "assignee, and optionally add a comment. If a field should not be "
                "changed, leave the argument null. State is validated against allowed "
                "values for the work item's type."
            ),
            args_schema=UpdateWorkItemArgs,
        ),
        StructuredTool.from_function(
            _create_work_item,
            name="create_work_item",
            description=(
                "Create a new Azure DevOps work item of the given type. Title is "
                "required; description is optional plain text. The area path defaults "
                "to the configured project area."
            ),
            args_schema=CreateWorkItemArgs,
        ),
        StructuredTool.from_function(
            _add_work_item_comment,
            name="add_work_item_comment",
            description="Add a discussion comment to an Azure DevOps work item by ID.",
            args_schema=AddWorkItemCommentArgs,
        ),
    ]


__all__ = ["build_ado_tools", "ADOClientError"]
