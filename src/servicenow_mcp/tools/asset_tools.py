"""manage_asset — base asset records (alm_asset and its classes).

Lists and counts stay with sn_query / sn_aggregate; this tool is for what those
cannot do safely: look one asset up by any identifier, and write it with every
value checked against the instance first (see services/asset.py).
"""

from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import asset as asset_service
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

_WRITE_FIELDS = (
    "asset_tag",
    "serial_number",
    "install_status",
    "substatus",
    "stockroom",
    "assigned_to",
    "location",
)


class ManageAssetParams(BaseModel):
    action: Literal["get", "create", "update", "transfer"] = Field(...)
    asset_id: Optional[str] = Field(default=None, description="sys_id, asset_tag or serial_number")
    asset_class: Optional[str] = Field(
        default=None, description="alm_asset child table for create (default alm_hardware)"
    )
    model: Optional[str] = Field(default=None, description="cmdb_model sys_id")
    model_category: Optional[str] = Field(
        default=None, description="cmdb_model_category sys_id; derived when the model has one"
    )
    asset_tag: Optional[str] = Field(default=None)
    serial_number: Optional[str] = Field(default=None)
    install_status: Optional[str] = Field(default=None, description="Code or label (In stock)")
    substatus: Optional[str] = Field(
        default=None, description="Code or label, must belong to install_status"
    )
    stockroom: Optional[str] = Field(
        default=None, description="alm_stockroom sys_id (transfer: the source)"
    )
    to_stockroom: Optional[str] = Field(default=None, description="Transfer destination sys_id")
    assigned_to: Optional[str] = Field(default=None, description="sys_user sys_id")
    location: Optional[str] = Field(default=None, description="cmn_location sys_id")
    asset_ids: Optional[List[str]] = Field(
        default=None, description="Assets to transfer (max 50), or model+quantity"
    )
    quantity: Optional[int] = Field(default=None, description="Transfer count of model")
    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"asset_id"}),
        "create": frozenset({"asset_class", "model", "model_category", "dry_run", *_WRITE_FIELDS}),
        "update": frozenset({"asset_id", "dry_run", *_WRITE_FIELDS}),
        "transfer": frozenset(
            {"stockroom", "to_stockroom", "asset_ids", "model", "quantity", "dry_run"}
        ),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageAssetParams":
        if self.action in ("get", "update") and not self.asset_id:
            raise ValueError(f"asset_id is required for action='{self.action}'")
        if self.action == "create" and not self.model:
            raise ValueError("model is required for action='create'")
        if self.action == "transfer" and not (self.stockroom and self.to_stockroom):
            raise ValueError("stockroom and to_stockroom are required for action='transfer'")
        return self


@register_tool(
    name="manage_asset",
    params=ManageAssetParams,
    description="Get/create/update an asset or transfer stock; values checked live. Lists: sn_query.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_asset(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageAssetParams,
) -> Dict[str, Any]:
    if params.action == "get":
        assert params.asset_id is not None
        return asset_service.get(config, auth_manager, asset_id=params.asset_id)
    fields = {f: getattr(params, f) for f in _WRITE_FIELDS}
    if params.action == "create":
        assert params.model is not None
        return asset_service.create(
            config,
            auth_manager,
            model=params.model,
            asset_class=params.asset_class,
            model_category=params.model_category,
            **fields,
        )
    if params.action == "update":
        assert params.asset_id is not None
        return asset_service.update(
            config, auth_manager, asset_id=params.asset_id, dry_run=params.dry_run, **fields
        )
    assert params.stockroom is not None and params.to_stockroom is not None
    return asset_service.transfer(
        config,
        auth_manager,
        from_stockroom=params.stockroom,
        to_stockroom=params.to_stockroom,
        asset_ids=params.asset_ids,
        model=params.model,
        quantity=params.quantity,
        dry_run=params.dry_run,
    )
