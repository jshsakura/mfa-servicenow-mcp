"""
Module entry point so the server runs as `python -m servicenow_mcp`.

This is the documented invocation for pip installs: it avoids the
pip-generated console-script .exe shim, which unsigned-binary policies on
Windows (Smart App Control) block.
"""

from servicenow_mcp.cli import main

if __name__ == "__main__":
    main()
