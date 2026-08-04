"""
Business rule tools for the ServiceNow MCP server.

Creating a business rule is the same single POST as a script include or a
scripted REST service — only the table and the field set differ. What is
specific to ``sys_script`` is that two of its fields decide whether the rule
ever runs, and neither says so when it is wrong; the service layer refuses
those combinations rather than writing an inert rule.
"""

import logging
from typing import Any, ClassVar, Dict, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import business_rule as _br_svc
from servicenow_mcp.services.business_rule import WHEN_VALUES, BusinessRuleResponse
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)

_BR_UPDATE_FIELDS = (
    "script",
    "condition",
    "filter_condition",
    "description",
    "collection",
    "when",
    "order",
    "active",
    "advanced",
    "action_insert",
    "action_update",
    "action_delete",
)


class ManageBusinessRuleParams(BaseModel):
    """Required per action:
    list:   (all optional)
    get:    business_rule_id
    create: name, collection, and at least one action_* (or when='display')
    update: business_rule_id, at least one field
    delete: business_rule_id
    """

    action: Literal["list", "get", "create", "update", "delete"] = Field(...)

    business_rule_id: Optional[str] = Field(
        default=None, description="sys_id, or rule name (add collection — names repeat)"
    )

    # list / get / disambiguation
    collection: Optional[str] = Field(default=None, description="Table the rule is attached to")
    limit: int = Field(default=20, description="Max records")
    offset: int = Field(default=0, description="Pagination offset")
    query: Optional[str] = Field(default=None, description="Name search")
    count_only: bool = Field(default=False, description="Return count only")

    # create / update
    name: Optional[str] = Field(default=None, description="Rule name")
    when: Optional[Literal["before", "after", "async", "display"]] = Field(
        default=None, description="Execution point. Default 'before' on create"
    )
    script: Optional[str] = Field(default=None, description="Rule script; implies advanced=true")
    condition: Optional[str] = Field(default=None, description="Condition script (JS expression)")
    filter_condition: Optional[str] = Field(default=None, description="Encoded query condition")
    description: Optional[str] = Field(default=None, description="What the rule does")
    order: Optional[int] = Field(default=None, description="Execution order. Default 100")
    active: Optional[bool] = Field(default=None, description="Whether the rule is active")
    advanced: Optional[bool] = Field(
        default=None, description="Run the script field. Auto-true when script is given"
    )
    action_insert: Optional[bool] = Field(default=None, description="Fire on insert")
    action_update: Optional[bool] = Field(default=None, description="Fire on update")
    action_delete: Optional[bool] = Field(default=None, description="Fire on delete")

    dry_run: bool = Field(default=False, description="Preview an update without writing")

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "list": frozenset(
            {"collection", "query", "when", "active", "limit", "offset", "count_only"}
        ),
        "get": frozenset({"business_rule_id", "collection"}),
        "create": frozenset(
            {
                "name",
                "collection",
                "when",
                "script",
                "condition",
                "filter_condition",
                "description",
                "order",
                "active",
                "advanced",
                "action_insert",
                "action_update",
                "action_delete",
            }
        ),
        "update": frozenset({"business_rule_id", "collection", "dry_run", *_BR_UPDATE_FIELDS}),
        "delete": frozenset({"business_rule_id", "collection"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageBusinessRuleParams":
        if self.action == "create":
            if not self.name:
                raise ValueError("name is required for action='create'")
            if not self.collection:
                raise ValueError("collection (the table) is required for action='create'")
        elif self.action in ("get", "update", "delete"):
            if not self.business_rule_id:
                raise ValueError(f"business_rule_id is required for action='{self.action}'")
            if self.action == "update" and not any(
                getattr(self, f) is not None for f in _BR_UPDATE_FIELDS
            ):
                raise ValueError("at least one field must be provided for action='update'")
        return self


@register_tool(
    name="manage_business_rule",
    params=ManageBusinessRuleParams,
    description="List/get/create/update/delete a business rule (sys_script). Names repeat across tables — pass collection.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_business_rule(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageBusinessRuleParams,
) -> Dict[str, Any]:
    if params.action == "list":
        return _br_svc.list_br(
            config,
            auth_manager,
            collection=params.collection,
            query=params.query,
            when=params.when,
            active=params.active,
            limit=params.limit,
            offset=params.offset,
            count_only=params.count_only,
        )

    if params.action == "get":
        assert params.business_rule_id is not None
        return _br_svc.get_br(
            config,
            auth_manager,
            business_rule_id=params.business_rule_id,
            collection=params.collection,
        )

    if params.action == "create":
        assert params.name is not None
        assert params.collection is not None
        created = _br_svc.create(
            config,
            auth_manager,
            name=params.name,
            collection=params.collection,
            when=params.when or "before",
            script=params.script,
            condition=params.condition,
            filter_condition=params.filter_condition,
            description=params.description,
            order=params.order if params.order is not None else 100,
            active=params.active if params.active is not None else True,
            advanced=params.advanced,
            action_insert=bool(params.action_insert),
            action_update=bool(params.action_update),
            action_delete=bool(params.action_delete),
        )
        return _dump(created)

    if params.action == "update":
        assert params.business_rule_id is not None
        changes = {f: getattr(params, f) for f in _BR_UPDATE_FIELDS}
        # `collection` doubles as the disambiguator for a repeated name and as a
        # field you may set. Only treat it as a move when the caller is not
        # merely using it to point at one of several same-named rules.
        updated = _br_svc.update(
            config,
            auth_manager,
            business_rule_id=params.business_rule_id,
            collection_filter=params.collection,
            dry_run=params.dry_run,
            **{**changes, "collection": None},
        )
        return _dump(updated)

    assert params.business_rule_id is not None
    return _dump(
        _br_svc.delete(
            config,
            auth_manager,
            business_rule_id=params.business_rule_id,
            collection_filter=params.collection,
        )
    )


def _dump(result: Any) -> Dict[str, Any]:
    if isinstance(result, BusinessRuleResponse):
        return result.model_dump(exclude_none=True)
    return result


__all__ = ["ManageBusinessRuleParams", "manage_business_rule", "WHEN_VALUES"]
