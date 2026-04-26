"""Unit tests for the kb_article service module.

Exercises ``servicenow_mcp.services.kb_article`` directly — without going
through the wrapper functions or the manage_kb_article dispatcher — so that
service behaviour is independently covered.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from servicenow_mcp.services import kb_article


def _ok_response(payload: dict) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    mock.json.return_value = payload
    mock.raise_for_status = MagicMock()
    return mock


@pytest.fixture
def auth(mock_auth):
    mock_auth.make_request = MagicMock()
    return mock_auth


# ----------------------------------------------------------------------
# create()
# ----------------------------------------------------------------------


@patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
def test_create_happy_path(mock_invalidate, mock_config, auth):
    auth.make_request.return_value = _ok_response(
        {"result": {"sys_id": "art1", "short_description": "T", "workflow_state": "draft"}}
    )

    result = kb_article.create(
        mock_config,
        auth,
        title="T",
        text="<p>x</p>",
        short_description="ignored-when-title-present",
        knowledge_base="kb1",
        category="cat1",
        keywords="k1",
        article_type="html",
    )

    assert result.success is True
    assert result.article_id == "art1"
    assert result.article_title == "T"
    assert result.workflow_state == "draft"
    mock_invalidate.assert_called_once_with(table="kb_knowledge")

    # title overrides short_description in the POST body
    sent = auth.make_request.call_args[1]["json"]
    assert sent["short_description"] == "T"
    assert sent["text"] == "<p>x</p>"
    assert sent["kb_knowledge_base"] == "kb1"
    assert sent["kb_category"] == "cat1"
    assert sent["article_type"] == "html"
    assert sent["keywords"] == "k1"


@patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
def test_create_without_title_uses_short_description(mock_invalidate, mock_config, auth):
    auth.make_request.return_value = _ok_response(
        {"result": {"sys_id": "art2", "short_description": "S", "workflow_state": "draft"}}
    )

    result = kb_article.create(
        mock_config,
        auth,
        title=None,
        text="body",
        short_description="S",
        knowledge_base="kb1",
        category="cat1",
    )

    assert result.success is True
    sent = auth.make_request.call_args[1]["json"]
    assert sent["short_description"] == "S"
    # Optional fields not sent when not provided
    assert "keywords" not in sent


def test_create_failure_returns_error_response(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("boom")

    with patch("servicenow_mcp.services.kb_article.invalidate_query_cache"):
        result = kb_article.create(
            mock_config,
            auth,
            title="T",
            text="x",
            short_description="s",
            knowledge_base="kb1",
            category="cat1",
        )

    assert result.success is False
    assert "Failed to create article" in result.message
    assert result.article_id is None


# ----------------------------------------------------------------------
# update()
# ----------------------------------------------------------------------


@patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
def test_update_happy_path(mock_invalidate, mock_config, auth):
    auth.make_request.return_value = _ok_response(
        {"result": {"sys_id": "art1", "short_description": "Updated", "workflow_state": "draft"}}
    )

    result = kb_article.update(
        mock_config,
        auth,
        article_id="art1",
        title="Updated",
        text="<p>new</p>",
        category="cat2",
        keywords="kw",
    )

    assert result.success is True
    assert result.article_id == "art1"
    assert result.article_title == "Updated"

    sent = auth.make_request.call_args[1]["json"]
    assert sent["short_description"] == "Updated"
    assert sent["text"] == "<p>new</p>"
    assert sent["kb_category"] == "cat2"
    assert sent["keywords"] == "kw"
    mock_invalidate.assert_called_once_with(table="kb_knowledge")


def test_update_short_description_explicit_overrides_title(mock_config, auth):
    """If both title and short_description are provided, the later assignment wins.

    The legacy wrapper executed ``data["short_description"] = title`` first, then
    ``data["short_description"] = short_description``, so short_description wins
    when both are present. Behaviour preserved.
    """
    auth.make_request.return_value = _ok_response({"result": {}})

    with patch("servicenow_mcp.services.kb_article.invalidate_query_cache"):
        kb_article.update(
            mock_config,
            auth,
            article_id="art1",
            title="From Title",
            short_description="From SD",
        )

    sent = auth.make_request.call_args[1]["json"]
    assert sent["short_description"] == "From SD"


def test_update_dry_run_returns_preview_without_calling_api(mock_config, auth):
    with patch("servicenow_mcp.services.kb_article.build_update_preview") as mock_preview:
        mock_preview.return_value = MagicMock(success=True)

        kb_article.update(
            mock_config,
            auth,
            article_id="art1",
            title="X",
            dry_run=True,
        )

    mock_preview.assert_called_once()
    auth.make_request.assert_not_called()


def test_update_failure_returns_error_response(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("net down")

    with patch("servicenow_mcp.services.kb_article.invalidate_query_cache"):
        result = kb_article.update(
            mock_config,
            auth,
            article_id="art1",
            title="X",
        )

    assert result.success is False
    assert "Failed to update article" in result.message


# ----------------------------------------------------------------------
# publish()
# ----------------------------------------------------------------------


@patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
def test_publish_happy_path(mock_invalidate, mock_config, auth):
    auth.make_request.return_value = _ok_response(
        {"result": {"sys_id": "art1", "short_description": "T", "workflow_state": "published"}}
    )

    result = kb_article.publish(
        mock_config,
        auth,
        article_id="art1",
        workflow_state="published",
    )

    assert result.success is True
    assert result.workflow_state == "published"
    sent = auth.make_request.call_args[1]["json"]
    assert sent["workflow_state"] == "published"
    assert "workflow_version" not in sent
    mock_invalidate.assert_called_once_with(table="kb_knowledge")


@patch("servicenow_mcp.services.kb_article.invalidate_query_cache")
def test_publish_with_workflow_version(_mock_invalidate, mock_config, auth):
    auth.make_request.return_value = _ok_response({"result": {}})

    kb_article.publish(
        mock_config,
        auth,
        article_id="art1",
        workflow_version="v2",
    )

    sent = auth.make_request.call_args[1]["json"]
    assert sent["workflow_version"] == "v2"
    # workflow_state default still applied
    assert sent["workflow_state"] == "published"


def test_publish_failure_returns_error_response(mock_config, auth):
    auth.make_request.side_effect = RuntimeError("503")

    with patch("servicenow_mcp.services.kb_article.invalidate_query_cache"):
        result = kb_article.publish(
            mock_config,
            auth,
            article_id="art1",
        )

    assert result.success is False
    assert "Failed to publish article" in result.message
