"""Fast JSON helpers — uses orjson when available, falls back to stdlib json."""

from __future__ import annotations

import json as _json
from typing import Any

try:
    import orjson as _orjson  # 2-4x faster than stdlib json

    def loads(data: str | bytes) -> Any:
        return _orjson.loads(data)

    def dumps(obj: Any, **kwargs: Any) -> str:
        # orjson.dumps returns bytes; callers expect str
        return _orjson.dumps(obj).decode("utf-8")

    BACKEND = "orjson"

except ImportError:

    def loads(data: str | bytes) -> Any:  # type: ignore[misc]
        return _json.loads(data)

    def dumps(obj: Any, **kwargs: Any) -> str:  # type: ignore[misc]
        kwargs.setdefault("separators", (",", ":"))
        return _json.dumps(obj, ensure_ascii=False, **kwargs)

    BACKEND = "json"
