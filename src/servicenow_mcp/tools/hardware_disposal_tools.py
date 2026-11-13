"""manage_hardware_disposal — HAM Pro hardware disposal orders, stage by stage.

The platform's own rules and the "Hardware Asset Disposal flow" run the order;
this tool makes the same moves the Hardware Asset Workspace makes and reads the
result back (see services/hardware_disposal.py).
"""

from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import hardware_disposal as svc
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

_STEPS = ("verify", "depart", "dispose")


class ManageHardwareDisposalParams(BaseModel):
    action: Literal[
        "get",
        "create",
        "add_assets",
        "verify",
        "depart",
        "dispose",
        "update",
        "attach_certificate",
        "complete_task",
    ] = Field(...)
    order: Optional[str] = Field(
        default=None, description="Disposal order number (HWDIS...) or sys_id"
    )
    asset_ids: Optional[List[str]] = Field(
        default=None, description="Assets by sys_id, tag or serial (steps: default all eligible)"
    )
    stockroom: Optional[str] = Field(default=None, description="alm_stockroom sys_id (create)")
    location: Optional[str] = Field(
        default=None, description="cmn_location sys_id (create; default the stockroom's)"
    )
    assigned_to: Optional[str] = Field(
        default=None, description="sys_user sys_id (create default: you; update)"
    )
    scheduled_date: Optional[str] = Field(
        default=None, description="Pickup date, YYYY-MM-DD HH:MM:SS"
    )
    vendor: Optional[str] = Field(
        default=None, description="core_company sys_id of the disposal vendor"
    )
    vendor_order_id: Optional[str] = Field(default=None)
    pickup_contact: Optional[str] = Field(default=None)
    pickup_details: Optional[str] = Field(default=None)
    carrier: Optional[str] = Field(default=None, description="Shipping carrier sys_id")
    tracking_number: Optional[str] = Field(default=None)
    shipped_to: Optional[str] = Field(default=None, description="cmn_location sys_id")
    additional_info: Optional[str] = Field(default=None)
    file_path: Optional[str] = Field(
        default=None, description="Local certificate file to attach (attach_certificate)"
    )
    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "get": frozenset({"order"}),
        "create": frozenset({"stockroom", "asset_ids", "location", "assigned_to", "dry_run"}),
        "add_assets": frozenset({"order", "asset_ids", "dry_run"}),
        "verify": frozenset({"order", "asset_ids", "dry_run"}),
        "depart": frozenset({"order", "asset_ids", "dry_run"}),
        "dispose": frozenset({"order", "asset_ids", "dry_run"}),
        "update": frozenset({"order", "dry_run", *svc.ORDER_FIELDS}),
        "attach_certificate": frozenset({"order", "file_path", "dry_run"}),
        "complete_task": frozenset({"order", "dry_run"}),
    }

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageHardwareDisposalParams":
        if self.action == "create":
            if not self.stockroom or not self.asset_ids:
                raise ValueError("stockroom and asset_ids are required for action='create'")
        elif not self.order:
            raise ValueError(f"order is required for action='{self.action}'")
        if self.action == "add_assets" and not self.asset_ids:
            raise ValueError("asset_ids is required for action='add_assets'")
        if self.action == "attach_certificate" and not self.file_path:
            raise ValueError("file_path is required for action='attach_certificate'")
        return self


@register_tool(
    name="manage_hardware_disposal",
    params=ManageHardwareDisposalParams,
    description="HAM Pro disposal order: create, add assets, verify/depart/dispose, close tasks. get shows what's next.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_hardware_disposal(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageHardwareDisposalParams,
) -> Dict[str, Any]:
    action = params.action
    if action == "create":
        assert params.stockroom is not None and params.asset_ids is not None
        return svc.create(
            config,
            auth_manager,
            stockroom=params.stockroom,
            asset_ids=params.asset_ids,
            location=params.location,
            assigned_to=params.assigned_to,
            dry_run=params.dry_run,
        )
    assert params.order is not None
    if action == "get":
        return svc.status(config, auth_manager, order=params.order)
    if action == "add_assets":
        return svc.add_assets(
            config,
            auth_manager,
            order=params.order,
            asset_ids=params.asset_ids or [],
            dry_run=params.dry_run,
        )
    if action in _STEPS:
        return svc.run_step(
            config,
            auth_manager,
            step=action,
            order=params.order,
            asset_ids=params.asset_ids,
            dry_run=params.dry_run,
        )
    if action == "update":
        fields: Dict[str, Any] = {
            "scheduled_date": params.scheduled_date,
            "vendor": params.vendor,
            "vendor_order_id": params.vendor_order_id,
            "pickup_contact": params.pickup_contact,
            "pickup_details": params.pickup_details,
            "carrier": params.carrier,
            "tracking_number": params.tracking_number,
            "shipped_to": params.shipped_to,
            "additional_info": params.additional_info,
            "assigned_to": params.assigned_to,
        }
        return svc.update(
            config, auth_manager, order=params.order, fields=fields, dry_run=params.dry_run
        )
    if action == "attach_certificate":
        assert params.file_path is not None
        return svc.attach_certificate(
            config,
            auth_manager,
            order=params.order,
            file_path=params.file_path,
            dry_run=params.dry_run,
        )
    return svc.complete_task(config, auth_manager, order=params.order, dry_run=params.dry_run)
