"""Compatibility resource interfaces for legacy tests and integrations."""

from servicenow_mcp.resources.catalog import (
    CatalogCategoryListParams,
    CatalogItemVariableModel,
    CatalogListParams,
    CatalogResource,
)
from servicenow_mcp.resources.changesets import ChangesetListParams, ChangesetResource
from servicenow_mcp.resources.script_includes import ScriptIncludeListParams, ScriptIncludeResource

__all__ = [
    "CatalogCategoryListParams",
    "CatalogItemVariableModel",
    "CatalogListParams",
    "CatalogResource",
    "ChangesetListParams",
    "ChangesetResource",
    "ScriptIncludeListParams",
    "ScriptIncludeResource",
]
