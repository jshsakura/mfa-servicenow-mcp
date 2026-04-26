"""Knowledge article (kb_knowledge) service layer.

Reusable API logic for create / update / publish operations against the
``kb_knowledge`` table. Both the public ``manage_kb_article`` MCP tool and the
legacy wrapper functions in ``servicenow_mcp.tools.knowledge_base`` call into
this module so behaviour stays in one place.

The ``ArticleResponse`` model lives here (rather than in the tools module) so
that anything in ``servicenow_mcp.tools.knowledge_base`` can import it without
creating an import cycle when wrappers route through services.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.tools._preview import build_update_preview
from servicenow_mcp.tools.sn_api import invalidate_query_cache
from servicenow_mcp.utils.config import ServerConfig

logger = logging.getLogger(__name__)


class ArticleResponse(BaseModel):
    """Response from knowledge article operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    article_id: Optional[str] = Field(default=None, description="ID of the affected article")
    article_title: Optional[str] = Field(default=None, description="Title of the affected article")
    workflow_state: Optional[str] = Field(
        default=None, description="Current workflow state of the article"
    )


def create(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    title: Optional[str],
    text: str,
    short_description: str,
    knowledge_base: str,
    category: str,
    keywords: Optional[str] = None,
    article_type: Optional[Literal["html", "text", "wiki"]] = "html",
) -> ArticleResponse:
    """Create a new knowledge article in the ``kb_knowledge`` table.

    Behavioural quirk preserved from the legacy ``create_article`` wrapper:
    when ``title`` is provided it overrides ``short_description`` in the
    POST payload (and therefore in the eventual ServiceNow record).
    """
    api_url = f"{config.api_url}/table/kb_knowledge"

    data: Dict[str, Any] = {
        "short_description": short_description,
        "text": text,
        "kb_knowledge_base": knowledge_base,
        "kb_category": category,
        "article_type": article_type,
    }

    if title:
        data["short_description"] = title
    if keywords:
        data["keywords"] = keywords

    try:
        response = auth_manager.make_request(
            "POST",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="kb_knowledge")

        return ArticleResponse(
            success=True,
            message="Article created successfully",
            article_id=result.get("sys_id"),
            article_title=result.get("short_description"),
            workflow_state=result.get("workflow_state"),
        )

    except Exception as e:
        logger.error(f"Failed to create article: {e}")
        return ArticleResponse(
            success=False,
            message=f"Failed to create article: {str(e)}",
        )


def update(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    article_id: str,
    title: Optional[str] = None,
    text: Optional[str] = None,
    short_description: Optional[str] = None,
    category: Optional[str] = None,
    keywords: Optional[str] = None,
    dry_run: bool = False,
) -> ArticleResponse:
    """Update an existing knowledge article. Supports a dry-run preview."""
    api_url = f"{config.api_url}/table/kb_knowledge/{article_id}"

    data: Dict[str, Any] = {}

    if title:
        data["short_description"] = title
    if text:
        data["text"] = text
    if short_description:
        data["short_description"] = short_description
    if category:
        data["kb_category"] = category
    if keywords:
        data["keywords"] = keywords

    if dry_run:
        return build_update_preview(
            config,
            auth_manager,
            table="kb_knowledge",
            sys_id=article_id,
            proposed=data,
            identifier_fields=["short_description", "kb_category", "workflow_state"],
        )

    try:
        response = auth_manager.make_request(
            "PATCH",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="kb_knowledge")

        return ArticleResponse(
            success=True,
            message="Article updated successfully",
            article_id=article_id,
            article_title=result.get("short_description"),
            workflow_state=result.get("workflow_state"),
        )

    except Exception as e:
        logger.error(f"Failed to update article: {e}")
        return ArticleResponse(
            success=False,
            message=f"Failed to update article: {str(e)}",
        )


def publish(
    config: ServerConfig,
    auth_manager: AuthManager,
    *,
    article_id: str,
    workflow_state: Optional[str] = "published",
    workflow_version: Optional[str] = None,
) -> ArticleResponse:
    """Publish a knowledge article by transitioning its workflow state."""
    api_url = f"{config.api_url}/table/kb_knowledge/{article_id}"

    data: Dict[str, Any] = {
        "workflow_state": workflow_state,
    }

    if workflow_version:
        data["workflow_version"] = workflow_version

    try:
        response = auth_manager.make_request(
            "PATCH",
            api_url,
            json=data,
            headers=auth_manager.get_headers(),
            timeout=config.timeout,
        )
        response.raise_for_status()

        result = response.json().get("result", {})
        invalidate_query_cache(table="kb_knowledge")

        return ArticleResponse(
            success=True,
            message="Article published successfully",
            article_id=article_id,
            article_title=result.get("short_description"),
            workflow_state=result.get("workflow_state"),
        )

    except Exception as e:
        logger.error(f"Failed to publish article: {e}")
        return ArticleResponse(
            success=False,
            message=f"Failed to publish article: {str(e)}",
        )
