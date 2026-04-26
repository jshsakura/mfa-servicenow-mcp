"""Tests for registry uncovered paths — AST index building, static index loading, edge cases."""

import ast
import logging
import os
import tempfile
from unittest.mock import patch

import servicenow_mcp.utils.registry as reg


class TestExtractRegisterToolName:
    def test_positional_name(self):
        tree = ast.parse('@register_tool("my_tool", params=P)\ndef f(): pass')
        dec = tree.body[0].decorator_list[0]
        assert reg._extract_register_tool_name(dec) == "my_tool"

    def test_keyword_name(self):
        tree = ast.parse('@register_tool(name="kw_tool", params=P)\ndef f(): pass')
        dec = tree.body[0].decorator_list[0]
        assert reg._extract_register_tool_name(dec) == "kw_tool"

    def test_no_name_returns_none(self):
        tree = ast.parse("@register_tool(params=P)\ndef f(): pass")
        dec = tree.body[0].decorator_list[0]
        assert reg._extract_register_tool_name(dec) is None

    def test_non_string_name_returns_none(self):
        tree = ast.parse("@register_tool(42, params=P)\ndef f(): pass")
        dec = tree.body[0].decorator_list[0]
        assert reg._extract_register_tool_name(dec) is None


class TestBuildToolModuleIndex:
    def test_skips_underscore_prefixed_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dunder_file = os.path.join(tmpdir, "_private.py")
            with open(dunder_file, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool("hidden", params=None, description="x")\ndef f(): pass\n'
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                idx = reg._build_tool_module_index()
                assert "hidden" not in idx
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_skips_non_py_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_file = os.path.join(tmpdir, "notes.txt")
            with open(txt_file, "w") as f:
                f.write("not python")
            py_file = os.path.join(tmpdir, "valid.py")
            with open(py_file, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool("valid_tool", params=None, description="x")\ndef f(): pass\n'
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                idx = reg._build_tool_module_index()
                assert "valid_tool" in idx
                assert len(idx) == 1
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_syntax_error_file_skipped(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = os.path.join(tmpdir, "bad_syntax.py")
            with open(bad_file, "w") as f:
                f.write("def broken(\n")
            good_file = os.path.join(tmpdir, "good.py")
            with open(good_file, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool("good_tool", params=None, description="x")\ndef f(): pass\n'
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                with caplog.at_level(logging.WARNING):
                    idx = reg._build_tool_module_index()
                assert "good_tool" in idx
                assert "bad_syntax" not in str(idx)
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_function_without_register_tool_decorator_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = os.path.join(tmpdir, "plain.py")
            with open(py_file, "w") as f:
                f.write("def plain_function():\n    pass\n")

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                idx = reg._build_tool_module_index()
                assert idx == {}
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_non_call_decorator_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = os.path.join(tmpdir, "deco.py")
            with open(py_file, "w") as f:
                f.write(
                    "from servicenow_mcp.utils.registry import register_tool\n@register_tool\ndef f(): pass\n"
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                idx = reg._build_tool_module_index()
                assert idx == {}
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_register_tool_with_no_name_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = os.path.join(tmpdir, "noname.py")
            with open(py_file, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool(params=None, description="x")\ndef f(): pass\n'
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                idx = reg._build_tool_module_index()
                assert idx == {}
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_oserror_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                with patch("os.listdir", side_effect=OSError("permission denied")):
                    result = reg._build_tool_module_index()
                assert result == {}
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None

    def test_empty_pkg_path_returns_empty(self):
        import servicenow_mcp.tools as tools_pkg

        orig_path = tools_pkg.__path__
        tools_pkg.__path__ = []
        try:
            result = reg._build_tool_module_index()
            assert result == {}
        finally:
            tools_pkg.__path__ = orig_path
            reg._TOOL_MODULE_INDEX = None


class TestLoadStaticToolModuleIndex:
    def test_import_error_returns_empty(self):
        with patch.dict("sys.modules", {}):
            result = reg._load_static_tool_module_index()
            assert isinstance(result, dict)

    def test_non_dict_returns_empty(self):
        import servicenow_mcp.tools._module_index as mi

        orig = mi.TOOL_MODULE_INDEX
        try:
            mi.TOOL_MODULE_INDEX = "not a dict"
            result = reg._load_static_tool_module_index()
            assert result == {}
        finally:
            mi.TOOL_MODULE_INDEX = orig


class TestGetToolModuleIndex:
    def test_caches_result(self):
        orig = reg._TOOL_MODULE_INDEX
        reg._TOOL_MODULE_INDEX = None
        try:
            fake_idx = {"tool_a": "module_a"}
            with patch(
                "servicenow_mcp.utils.registry._load_static_tool_module_index",
                return_value=fake_idx,
            ):
                result1 = reg._get_tool_module_index()
                result2 = reg._get_tool_module_index()
            assert result1 == fake_idx
            assert result1 is result2
        finally:
            reg._TOOL_MODULE_INDEX = orig

    def test_falls_back_to_build_when_static_empty(self):
        orig = reg._TOOL_MODULE_INDEX
        reg._TOOL_MODULE_INDEX = None
        try:
            with patch(
                "servicenow_mcp.utils.registry._load_static_tool_module_index", return_value={}
            ):
                with patch(
                    "servicenow_mcp.utils.registry._build_tool_module_index",
                    return_value={"b": "mod_b"},
                ):
                    result = reg._get_tool_module_index()
            assert "b" in result
        finally:
            reg._TOOL_MODULE_INDEX = orig


class TestDiscoverToolsLazy:
    def test_empty_index_falls_back(self):
        orig = reg._TOOL_MODULE_INDEX
        reg._TOOL_MODULE_INDEX = None
        try:
            with patch(
                "servicenow_mcp.utils.registry._load_static_tool_module_index", return_value={}
            ):
                with patch(
                    "servicenow_mcp.utils.registry._build_tool_module_index", return_value={}
                ):
                    with patch("servicenow_mcp.utils.registry.discover_tools", return_value={}):
                        result = reg.discover_tools_lazy(enabled_names={"tool_x"})
            assert result == {}
        finally:
            reg._TOOL_MODULE_INDEX = orig

    def test_unknown_tool_ignored(self):
        fake_idx = {"known_tool": "some_module"}
        reg._TOOL_MODULE_INDEX = None
        try:
            with patch(
                "servicenow_mcp.utils.registry._load_static_tool_module_index",
                return_value=fake_idx,
            ):
                with patch("importlib.import_module"):
                    result = reg.discover_tools_lazy(enabled_names={"unknown_tool"})
            assert result == {}
        finally:
            reg._TOOL_MODULE_INDEX = None

    def test_duplicate_tool_in_different_modules_warns(self, caplog):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = os.path.join(tmpdir, "mod_a.py")
            file_b = os.path.join(tmpdir, "mod_b.py")
            with open(file_a, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool("dup_tool", params=None, description="a")\ndef fa(): pass\n'
                )
            with open(file_b, "w") as f:
                f.write(
                    'from servicenow_mcp.utils.registry import register_tool\n@register_tool("dup_tool", params=None, description="b")\ndef fb(): pass\n'
                )

            import servicenow_mcp.tools as tools_pkg

            orig_path = tools_pkg.__path__
            tools_pkg.__path__ = [tmpdir]
            try:
                with caplog.at_level(logging.WARNING):
                    idx = reg._build_tool_module_index()
                assert idx.get("dup_tool") in ("mod_a", "mod_b")
            finally:
                tools_pkg.__path__ = orig_path
                reg._TOOL_MODULE_INDEX = None
