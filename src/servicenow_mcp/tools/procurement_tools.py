"""manage_procurement — receive hardware against a purchase order line.

Platform procurement (proc_po / proc_rec_slip), not a plugin flow. It calls the
Receive page's own server path, so the platform creates the assets and moves the
line's quantities; the Table API cannot (see services/procurement.py).
"""

from typing import Any, ClassVar, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import procurement as procurement_service
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool


class ManageProcurementParams(BaseModel):
    action: Literal["receive"] = Field(...)
    po_line: str = Field(..., description="proc_po_item sys_id or number (POL...)")
    quantity: int = Field(..., description="Units to receive; at most what the line has left")
    stockroom: Optional[str] = Field(
        default=None, description="alm_stockroom sys_id (default: the order's ship-to)"
    )
    serial_numbers: Optional[List[str]] = Field(
        default=None,
        description="One per unit, in order; required when the Receive page requires it",
    )
    asset_tags: Optional[List[str]] = Field(default=None, description="One per unit, in order")
    requested_for: Optional[str] = Field(
        default=None, description="sys_user sys_id the assets are reserved for"
    )
    reserve: bool = Field(default=False, description="Set the received assets to Reserved")
    dry_run: bool = Field(default=False)

    _FIELDS_BY_ACTION: ClassVar[Dict[str, frozenset]] = {
        "receive": frozenset(
            {
                "po_line",
                "quantity",
                "stockroom",
                "serial_numbers",
                "asset_tags",
                "requested_for",
                "reserve",
                "dry_run",
            }
        ),
    }


@register_tool(
    name="manage_procurement",
    params=ManageProcurementParams,
    description="Receive hardware on a PO line via the Receive page (browser auth); returns the assets created.",
    serialization="raw_dict",
    return_type=Dict[str, Any],
)
def manage_procurement(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageProcurementParams,
) -> Dict[str, Any]:
    if params.action != "receive":  # the Literal admits only receive today
        return {"success": False, "error": "UNKNOWN_ACTION", "message": params.action}
    return procurement_service.receive(
        config,
        auth_manager,
        po_line=params.po_line,
        quantity=params.quantity,
        stockroom=params.stockroom,
        serial_numbers=params.serial_numbers,
        asset_tags=params.asset_tags,
        requested_for=params.requested_for,
        reserve=params.reserve,
        dry_run=params.dry_run,
    )
