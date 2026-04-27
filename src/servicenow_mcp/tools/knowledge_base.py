"""
Knowledge base tools for the ServiceNow MCP server.

This module provides tools for managing knowledge bases, categories, and articles in ServiceNow.
"""

import logging
from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

from servicenow_mcp.auth.auth_manager import AuthManager
from servicenow_mcp.services import kb_article as kb_article_service
from servicenow_mcp.services.kb_article import ArticleResponse
from servicenow_mcp.tools.sn_api import invalidate_query_cache, sn_query_page
from servicenow_mcp.utils.config import ServerConfig
from servicenow_mcp.utils.registry import register_tool

logger = logging.getLogger(__name__)


class CreateKnowledgeBaseParams(BaseModel):
    """Parameters for creating a knowledge base."""

    title: str = Field(..., description="Title of the knowledge base")
    description: Optional[str] = Field(
        default=None, description="Description of the knowledge base"
    )
    owner: Optional[str] = Field(default=None, description="The specified admin user or group")
    managers: Optional[str] = Field(
        default=None, description="Users who can manage this knowledge base"
    )
    publish_workflow: Optional[str] = Field(
        default="Knowledge - Instant Publish", description="Publication workflow"
    )
    retire_workflow: Optional[str] = Field(
        default="Knowledge - Instant Retire", description="Retirement workflow"
    )


class ListKnowledgeBasesParams(BaseModel):
    """Parameters for listing knowledge bases."""

    limit: int = Field(default=10, description="Maximum number of knowledge bases to return")
    offset: int = Field(default=0, description="Offset for pagination")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    query: Optional[str] = Field(default=None, description="Search query for knowledge bases")


class CreateCategoryParams(BaseModel):
    """Parameters for creating a category in a knowledge base."""

    title: str = Field(..., description="Title of the category")
    description: Optional[str] = Field(default=None, description="Description of the category")
    knowledge_base: str = Field(..., description="The knowledge base to create the category in")
    parent_category: Optional[str] = Field(
        default=None,
        description="Parent category (if creating a subcategory). Sys_id refering to the parent category or sys_id of the parent table.",
    )
    parent_table: Optional[str] = Field(
        default=None,
        description="Parent table (if creating a subcategory). Sys_id refering to the table where the parent category is defined.",
    )
    active: bool = Field(default=True, description="Whether the category is active")


class ListArticlesParams(BaseModel):
    """Parameters for listing knowledge articles."""

    limit: int = Field(default=10, description="Maximum number of articles to return")
    offset: int = Field(default=0, description="Offset for pagination")
    knowledge_base: Optional[str] = Field(default=None, description="Filter by knowledge base")
    category: Optional[str] = Field(default=None, description="Filter by category")
    query: Optional[str] = Field(default=None, description="Search query for articles")
    workflow_state: Optional[str] = Field(default=None, description="Filter by workflow state")


class GetArticleParams(BaseModel):
    """Parameters for getting a knowledge article."""

    article_id: str = Field(..., description="ID of the article to get")


class KnowledgeBaseResponse(BaseModel):
    """Response from knowledge base operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    kb_id: Optional[str] = Field(default=None, description="ID of the affected knowledge base")
    kb_name: Optional[str] = Field(default=None, description="Name of the affected knowledge base")


class CategoryResponse(BaseModel):
    """Response from category operations."""

    success: bool = Field(..., description="Whether the operation was successful")
    message: str = Field(..., description="Message describing the result")
    category_id: Optional[str] = Field(default=None, description="ID of the affected category")
    category_name: Optional[str] = Field(default=None, description="Name of the affected category")


class ListCategoriesParams(BaseModel):
    """Parameters for listing categories in a knowledge base."""

    knowledge_base: Optional[str] = Field(default=None, description="Filter by knowledge base ID")
    parent_category: Optional[str] = Field(default=None, description="Filter by parent category ID")
    limit: int = Field(default=10, description="Maximum number of categories to return")
    offset: int = Field(default=0, description="Offset for pagination")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    query: Optional[str] = Field(default=None, description="Search query for categories")


@register_tool(
    "create_knowledge_base",
    params=CreateKnowledgeBaseParams,
    description="Create a knowledge base (kb_knowledge_base). Requires title. Returns sys_id.",
    serialization="json_dict",
    return_type=str,
)
def create_knowledge_base(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateKnowledgeBaseParams,
) -> KnowledgeBaseResponse:
    """
    Create a new knowledge base in ServiceNow.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the knowledge base.

    Returns:
        Response with the created knowledge base details.
    """
    api_url = f"{config.api_url}/table/kb_knowledge_base"

    # Build request data
    data = {
        "title": params.title,
    }

    if params.description:
        data["description"] = params.description
    if params.owner:
        data["owner"] = params.owner
    if params.managers:
        data["kb_managers"] = params.managers
    if params.publish_workflow:
        data["workflow_publish"] = params.publish_workflow
    if params.retire_workflow:
        data["workflow_retire"] = params.retire_workflow

    # Make request
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
        invalidate_query_cache(table="kb_knowledge_base")

        return KnowledgeBaseResponse(
            success=True,
            message="Knowledge base created successfully",
            kb_id=result.get("sys_id"),
            kb_name=result.get("title"),
        )

    except Exception as e:
        logger.error(f"Failed to create knowledge base: {e}")
        return KnowledgeBaseResponse(
            success=False,
            message=f"Failed to create knowledge base: {str(e)}",
        )


def list_knowledge_bases(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListKnowledgeBasesParams,
) -> Dict[str, Any]:
    """
    List knowledge bases with filtering options.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing knowledge bases.

    Returns:
        Dictionary with list of knowledge bases and metadata.
    """
    # Build query string
    query_parts = []
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.query:
        query_parts.append(f"titleLIKE{params.query}^ORdescriptionLIKE{params.query}")

    query = "^".join(query_parts)

    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="kb_knowledge_base",
            query=query,
            fields="sys_id,title,description,owner,kb_managers,active,sys_created_on,sys_updated_on",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )

        # Transform the results - create a simpler structure
        knowledge_bases = []

        # Handle either string or list
        if isinstance(result, list):
            for kb_item in result:
                if not isinstance(kb_item, dict):
                    logger.warning("Skipping non-dictionary KB item: %s", kb_item)
                    continue

                # Safely extract values
                kb_id = kb_item.get("sys_id", "")
                title = kb_item.get("title", "")
                description = kb_item.get("description", "")

                # Extract nested values safely
                owner = ""
                if isinstance(kb_item.get("owner"), dict):
                    owner = kb_item["owner"].get("display_value", "")

                managers = ""
                if isinstance(kb_item.get("kb_managers"), dict):
                    managers = kb_item["kb_managers"].get("display_value", "")

                active = False
                if kb_item.get("active") == "true":
                    active = True

                created = kb_item.get("sys_created_on", "")
                updated = kb_item.get("sys_updated_on", "")

                knowledge_bases.append(
                    {
                        "id": kb_id,
                        "title": title,
                        "description": description,
                        "owner": owner,
                        "managers": managers,
                        "active": active,
                        "created": created,
                        "updated": updated,
                    }
                )
        else:
            logger.warning("Result is not a list: %s", result)

        return {
            "success": True,
            "message": f"Found {len(knowledge_bases)} knowledge bases",
            "knowledge_bases": knowledge_bases,
            "count": len(knowledge_bases),
            "limit": params.limit,
            "offset": params.offset,
        }

    except Exception as e:
        logger.error(f"Failed to list knowledge bases: {e}")
        return {
            "success": False,
            "message": f"Failed to list knowledge bases: {str(e)}",
            "knowledge_bases": [],
            "count": 0,
            "limit": params.limit,
            "offset": params.offset,
        }


@register_tool(
    "create_category",
    params=CreateCategoryParams,
    description="Create a KB category under a knowledge base. Requires kb_id and label.",
    serialization="json_dict",
    return_type=str,
)
def create_category(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: CreateCategoryParams,
) -> CategoryResponse:
    """
    Create a new category in a knowledge base.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for creating the category.

    Returns:
        Response with the created category details.
    """
    api_url = f"{config.api_url}/table/kb_category"

    # Build request data
    data = {
        "label": params.title,
        "kb_knowledge_base": params.knowledge_base,
        # Convert boolean to string "true"/"false" as ServiceNow expects
        "active": str(params.active).lower(),
    }

    if params.description:
        data["description"] = params.description
    if params.parent_category:
        data["parent"] = params.parent_category
    if params.parent_table:
        data["parent_table"] = params.parent_table

    # Log the request data for debugging
    logger.debug(f"Creating category with data: {data}")

    # Make request
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
        logger.debug(f"Category creation response: {result}")
        invalidate_query_cache(table="kb_category")

        # Log the specific fields to check the knowledge base assignment
        if "kb_knowledge_base" in result:
            logger.debug(f"Knowledge base in response: {result['kb_knowledge_base']}")

        # Log the active status
        if "active" in result:
            logger.debug(f"Active status in response: {result['active']}")

        return CategoryResponse(
            success=True,
            message="Category created successfully",
            category_id=result.get("sys_id"),
            category_name=result.get("label"),
        )

    except Exception as e:
        logger.error(f"Failed to create category: {e}")
        return CategoryResponse(
            success=False,
            message=f"Failed to create category: {str(e)}",
        )


def list_articles(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListArticlesParams,
) -> Dict[str, Any]:
    """
    List knowledge articles with filtering options.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing articles.

    Returns:
        Dictionary with list of articles and metadata.
    """
    # Build query string
    query_parts = []
    if params.knowledge_base:
        query_parts.append(f"kb_knowledge_base.sys_id={params.knowledge_base}")
    if params.category:
        query_parts.append(f"kb_category.sys_id={params.category}")
    if params.workflow_state:
        query_parts.append(f"workflow_state={params.workflow_state}")
    if params.query:
        query_parts.append(f"short_descriptionLIKE{params.query}^ORtextLIKE{params.query}")

    query = "^".join(query_parts)
    logger.debug("Constructed article query string: %s", query)

    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="kb_knowledge",
            query=query,
            fields="sys_id,short_description,kb_knowledge_base,kb_category,workflow_state,sys_created_on,sys_updated_on",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )

        # Transform the results
        articles = []

        # Handle either string or list
        if isinstance(result, list):
            for article_item in result:
                if not isinstance(article_item, dict):
                    logger.warning("Skipping non-dictionary article item: %s", article_item)
                    continue

                # Safely extract values
                article_id = article_item.get("sys_id", "")
                title = article_item.get("short_description", "")

                # Extract nested values safely
                knowledge_base = ""
                if isinstance(article_item.get("kb_knowledge_base"), dict):
                    knowledge_base = article_item["kb_knowledge_base"].get("display_value", "")

                category = ""
                if isinstance(article_item.get("kb_category"), dict):
                    category = article_item["kb_category"].get("display_value", "")

                workflow_state = ""
                if isinstance(article_item.get("workflow_state"), dict):
                    workflow_state = article_item["workflow_state"].get("display_value", "")

                created = article_item.get("sys_created_on", "")
                updated = article_item.get("sys_updated_on", "")

                articles.append(
                    {
                        "id": article_id,
                        "title": title,
                        "knowledge_base": knowledge_base,
                        "category": category,
                        "workflow_state": workflow_state,
                        "created": created,
                        "updated": updated,
                    }
                )
        else:
            logger.warning("Result is not a list: %s", result)

        return {
            "success": True,
            "message": f"Found {len(articles)} articles",
            "articles": articles,
            "count": len(articles),
            "limit": params.limit,
            "offset": params.offset,
        }

    except Exception as e:
        logger.error(f"Failed to list articles: {e}")
        return {
            "success": False,
            "message": f"Failed to list articles: {str(e)}",
            "articles": [],
            "count": 0,
            "limit": params.limit,
            "offset": params.offset,
        }


def get_article(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: GetArticleParams,
) -> Dict[str, Any]:
    """
    Get a specific knowledge article by ID.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for getting the article.

    Returns:
        Dictionary with article details.
    """
    try:
        rows, _ = sn_query_page(
            config,
            auth_manager,
            table="kb_knowledge",
            query=f"sys_id={params.article_id}",
            fields="sys_id,short_description,text,kb_knowledge_base,kb_category,workflow_state,sys_created_on,sys_updated_on,author,keywords,article_type,view_count",
            limit=1,
            offset=0,
            display_value=True,
            fail_silently=False,
        )
        if isinstance(rows, list):
            result = rows[0] if rows else {}
        elif isinstance(rows, dict):
            result = rows
        else:
            result = {}

        if not result or not isinstance(result, dict):
            return {
                "success": False,
                "message": f"Article with ID {params.article_id} not found",
            }

        # Extract values safely
        article_id = result.get("sys_id", "")
        title = result.get("short_description", "")
        text = result.get("text", "")

        # Extract nested values safely
        knowledge_base = ""
        if isinstance(result.get("kb_knowledge_base"), dict):
            knowledge_base = result["kb_knowledge_base"].get("display_value", "")

        category = ""
        if isinstance(result.get("kb_category"), dict):
            category = result["kb_category"].get("display_value", "")

        workflow_state = ""
        if isinstance(result.get("workflow_state"), dict):
            workflow_state = result["workflow_state"].get("display_value", "")

        author = ""
        if isinstance(result.get("author"), dict):
            author = result["author"].get("display_value", "")

        keywords = result.get("keywords", "")
        article_type = result.get("article_type", "")
        views = result.get("view_count", "0")
        created = result.get("sys_created_on", "")
        updated = result.get("sys_updated_on", "")

        article = {
            "id": article_id,
            "title": title,
            "text": text,
            "knowledge_base": knowledge_base,
            "category": category,
            "workflow_state": workflow_state,
            "created": created,
            "updated": updated,
            "author": author,
            "keywords": keywords,
            "article_type": article_type,
            "views": views,
        }

        return {
            "success": True,
            "message": "Article retrieved successfully",
            "article": article,
        }

    except Exception as e:
        logger.error(f"Failed to get article: {e}")
        return {
            "success": False,
            "message": f"Failed to get article: {str(e)}",
        }


def list_categories(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ListCategoriesParams,
) -> Dict[str, Any]:
    """
    List categories in a knowledge base.

    Args:
        config: Server configuration.
        auth_manager: Authentication manager.
        params: Parameters for listing categories.

    Returns:
        Dictionary with list of categories and metadata.
    """
    # Build query string
    query_parts = []
    if params.knowledge_base:
        # Try different query format to ensure we match by sys_id value
        query_parts.append(f"kb_knowledge_base.sys_id={params.knowledge_base}")
    if params.parent_category:
        query_parts.append(f"parent.sys_id={params.parent_category}")
    if params.active is not None:
        query_parts.append(f"active={str(params.active).lower()}")
    if params.query:
        query_parts.append(f"labelLIKE{params.query}^ORdescriptionLIKE{params.query}")

    query = "^".join(query_parts)
    logger.debug("Constructed query string: %s", query)

    try:
        result, _ = sn_query_page(
            config,
            auth_manager,
            table="kb_category",
            query=query,
            fields="sys_id,label,description,kb_knowledge_base,parent,active,sys_created_on,sys_updated_on",
            limit=min(params.limit, 100),
            offset=params.offset,
            display_value=True,
            fail_silently=False,
        )

        # Transform the results
        categories = []

        # Handle either string or list
        if isinstance(result, list):
            for category_item in result:
                if not isinstance(category_item, dict):
                    logger.warning("Skipping non-dictionary category item: %s", category_item)
                    continue

                # Safely extract values
                category_id = category_item.get("sys_id", "")
                title = category_item.get("label", "")
                description = category_item.get("description", "")

                # Extract knowledge base - handle both dictionary and string cases
                knowledge_base = ""
                kb_field = category_item.get("kb_knowledge_base")
                if isinstance(kb_field, dict):
                    knowledge_base = kb_field.get("display_value", "")
                elif isinstance(kb_field, str):
                    knowledge_base = kb_field
                # Also check if kb_knowledge_base is missing but there's a separate value field
                elif "kb_knowledge_base_value" in category_item:
                    knowledge_base = category_item.get("kb_knowledge_base_value", "")
                elif "kb_knowledge_base.display_value" in category_item:
                    knowledge_base = category_item.get("kb_knowledge_base.display_value", "")

                # Extract parent category - handle both dictionary and string cases
                parent = ""
                parent_field = category_item.get("parent")
                if isinstance(parent_field, dict):
                    parent = parent_field.get("display_value", "")
                elif isinstance(parent_field, str):
                    parent = parent_field
                # Also check alternative field names
                elif "parent_value" in category_item:
                    parent = category_item.get("parent_value", "")
                elif "parent.display_value" in category_item:
                    parent = category_item.get("parent.display_value", "")

                # Convert active to boolean - handle string or boolean types
                active_field = category_item.get("active")
                if isinstance(active_field, str):
                    active = active_field.lower() == "true"
                elif isinstance(active_field, bool):
                    active = active_field
                else:
                    active = False

                created = category_item.get("sys_created_on", "")
                updated = category_item.get("sys_updated_on", "")

                categories.append(
                    {
                        "id": category_id,
                        "title": title,
                        "description": description,
                        "knowledge_base": knowledge_base,
                        "parent_category": parent,
                        "active": active,
                        "created": created,
                        "updated": updated,
                    }
                )

                # Log for debugging purposes
                logger.debug(f"Processed category: {title}, KB: {knowledge_base}, Parent: {parent}")
        else:
            logger.warning("Result is not a list: %s", result)

        return {
            "success": True,
            "message": f"Found {len(categories)} categories",
            "categories": categories,
            "count": len(categories),
            "limit": params.limit,
            "offset": params.offset,
        }

    except Exception as e:
        logger.error(f"Failed to list categories: {e}")
        return {
            "success": False,
            "message": f"Failed to list categories: {str(e)}",
            "categories": [],
            "count": 0,
            "limit": params.limit,
            "offset": params.offset,
        }


# ---------------------------------------------------------------------------
# manage_kb_article — bundled CRUD for knowledge articles
# ---------------------------------------------------------------------------


class ManageKbArticleParams(BaseModel):
    """Manage KB articles — table: kb_knowledge.

    Required per action:
      create:  title, text, short_description, knowledge_base, category
      update:  article_id, at least one field
      publish: article_id
    """

    action: Literal[
        "list_kbs",
        "list_articles",
        "get_article",
        "list_categories",
        "create",
        "update",
        "publish",
    ] = Field(...)
    article_id: Optional[str] = Field(
        default=None, description="sys_id for get_article/update/publish"
    )

    # Read params (list_kbs/list_articles/list_categories)
    limit: int = Field(default=10, description="Max records (list modes)")
    offset: int = Field(default=0, description="Pagination offset (list modes)")
    query: Optional[str] = Field(default=None, description="Search query (list modes)")
    active: Optional[bool] = Field(default=None, description="Filter by active status")
    workflow_state: Optional[str] = Field(default=None, description="Filter/publish target state")
    parent_category: Optional[str] = Field(
        default=None, description="Filter by parent category (list_categories)"
    )

    # Create-only required
    title: Optional[str] = Field(default=None)
    text: Optional[str] = Field(default=None)
    short_description: Optional[str] = Field(default=None)
    knowledge_base: Optional[str] = Field(
        default=None, description="KB sys_id (create/list_articles/list_categories)"
    )
    category: Optional[str] = Field(
        default=None, description="Category sys_id (create/list_articles)"
    )
    keywords: Optional[str] = Field(default=None)
    article_type: Optional[Literal["html", "text", "wiki"]] = Field(
        default=None, description="Article body markup type (create)"
    )

    # Publish-specific
    workflow_version: Optional[str] = Field(default=None)

    dry_run: bool = Field(default=False)

    @model_validator(mode="after")
    def _validate_per_action(self) -> "ManageKbArticleParams":
        if self.action in ("list_kbs", "list_articles", "get_article", "list_categories"):
            pass
        elif self.action == "create":
            missing = [
                f
                for f in ("title", "text", "short_description", "knowledge_base", "category")
                if getattr(self, f) is None
            ]
            if missing:
                raise ValueError(f"action='create' requires: {', '.join(missing)}")
        elif self.action == "update":
            if not self.article_id:
                raise ValueError("article_id is required for action='update'")
            if not any(
                getattr(self, f) is not None
                for f in ("title", "text", "short_description", "category", "keywords")
            ):
                raise ValueError("at least one field must be provided for action='update'")
        elif self.action == "publish":
            if not self.article_id:
                raise ValueError("article_id is required for action='publish'")
        return self


@register_tool(
    "manage_kb_article",
    params=ManageKbArticleParams,
    description="Create/update/publish a knowledge article (table: kb_knowledge).",
    serialization="json_dict",
    return_type=str,
)
def manage_kb_article(
    config: ServerConfig,
    auth_manager: AuthManager,
    params: ManageKbArticleParams,
) -> Union[ArticleResponse, Dict[str, Any]]:
    a = params.action
    if a == "list_kbs":
        return list_knowledge_bases(
            config,
            auth_manager,
            ListKnowledgeBasesParams(
                limit=params.limit, offset=params.offset, active=params.active, query=params.query
            ),
        )
    if a == "list_articles":
        return list_articles(
            config,
            auth_manager,
            ListArticlesParams(
                limit=params.limit,
                offset=params.offset,
                knowledge_base=params.knowledge_base,
                category=params.category,
                query=params.query,
                workflow_state=params.workflow_state,
            ),
        )
    if a == "get_article":
        if not params.article_id:
            return ArticleResponse(
                success=False, message="article_id is required for action='get_article'"
            )
        return get_article(config, auth_manager, GetArticleParams(article_id=params.article_id))
    if a == "list_categories":
        return list_categories(
            config,
            auth_manager,
            ListCategoriesParams(
                limit=params.limit,
                offset=params.offset,
                knowledge_base=params.knowledge_base,
                parent_category=params.parent_category,
                active=params.active,
                query=params.query,
            ),
        )
    if params.action == "create":
        # Preserve legacy defaulting: omit keywords/article_type when caller didn't
        # supply them so the service-layer defaults (None / "html") apply.
        kwargs: Dict[str, Any] = {
            "title": params.title,
            "text": params.text,
            "short_description": params.short_description,
            "knowledge_base": params.knowledge_base,
            "category": params.category,
        }
        if params.keywords is not None:
            kwargs["keywords"] = params.keywords
        if params.article_type is not None:
            kwargs["article_type"] = params.article_type
        return kb_article_service.create(config, auth_manager, **kwargs)

    if params.action == "update":
        # ManageArticleParams validator guarantees article_id is present for update.
        assert params.article_id is not None
        return kb_article_service.update(
            config,
            auth_manager,
            article_id=params.article_id,
            title=params.title,
            text=params.text,
            short_description=params.short_description,
            category=params.category,
            keywords=params.keywords,
            dry_run=params.dry_run,
        )

    # publish — only forward workflow_state/version when caller supplied them so
    # the service-layer default ("published") applies otherwise.
    pub_kwargs: Dict[str, Any] = {"article_id": params.article_id}
    if params.workflow_state is not None:
        pub_kwargs["workflow_state"] = params.workflow_state
    if params.workflow_version is not None:
        pub_kwargs["workflow_version"] = params.workflow_version
    return kb_article_service.publish(config, auth_manager, **pub_kwargs)
