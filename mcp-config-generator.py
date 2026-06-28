#!/usr/bin/env python3
"""
XRAY MCP Configuration Generator
Generates MCP config for different tools and installation methods.
"""

import json
import sys
from pathlib import Path

ConfigPayload = dict[str, object]
ConfigMethods = dict[str, ConfigPayload]

CONFIGS: dict[str, ConfigMethods] = {
    "cursor": {
        "local_python": {"mcpServers": {"xray": {"command": "uv", "args": ["run", "python", "-m", "xray.mcp_server"]}}},
        "docker": {"mcpServers": {"xray": {"command": "docker", "args": ["run", "--rm", "-i", "xray"]}}},
        "source": {"mcpServers": {"xray": {"command": "uv", "args": ["run", "xray-mcp"], "cwd": str(Path.cwd())}}},
        "installed_script": {"mcpServers": {"xray": {"command": "xray-mcp"}}},
    },
    "claude": {
        "local_python": {"mcpServers": {"xray": {"command": "uv", "args": ["run", "python", "-m", "xray.mcp_server"]}}},
        "docker": {"mcpServers": {"xray": {"command": "docker", "args": ["run", "--rm", "-i", "xray"]}}},
        "installed_script": {"mcpServers": {"xray": {"command": "xray-mcp"}}},
    },
    "vscode": {
        "local_python": {
            "mcp": {
                "servers": {
                    "xray": {"type": "stdio", "command": "uv", "args": ["run", "python", "-m", "xray.mcp_server"]}
                }
            }
        },
        "docker": {
            "mcp": {"servers": {"xray": {"type": "stdio", "command": "docker", "args": ["run", "--rm", "-i", "xray"]}}}
        },
        "source": {
            "mcp": {
                "servers": {
                    "xray": {"type": "stdio", "command": "uv", "args": ["run", "xray-mcp"], "cwd": str(Path.cwd())}
                }
            }
        },
        "installed_script": {"mcp": {"servers": {"xray": {"type": "stdio", "command": "xray-mcp"}}}},
    },
}

EXPECTED_ARG_COUNT = 3


def print_config(tool: str, method: str) -> bool:
    """Print MCP configuration for specified tool and method."""
    if tool not in CONFIGS:
        print(f"❌ Unknown tool: {tool}")
        print(f"Available tools: {', '.join(CONFIGS.keys())}")
        return False

    if method not in CONFIGS[tool]:
        print(f"❌ Unknown method: {method}")
        print(f"Available methods for {tool}: {', '.join(CONFIGS[tool].keys())}")
        return False

    config = CONFIGS[tool][method]
    print(f"🔧 {tool.title()} configuration ({method.replace('_', ' ')}):")
    print()
    print(json.dumps(config, indent=2))
    print()

    # Add helpful instructions
    if tool == "cursor":
        print("📝 Add this to your Cursor ~/.cursor/mcp.json file")
    elif tool == "claude":
        print("📝 Add this to your Claude desktop config:")
        print("   macOS: ~/Library/Application Support/Claude/claude_desktop_config.json")
        print("   Windows: %APPDATA%\\Claude\\claude_desktop_config.json")
    elif tool == "vscode":
        print("📝 Add this to your VS Code settings.json file")

    return True


def main() -> int:
    if len(sys.argv) != EXPECTED_ARG_COUNT:
        print("XRAY MCP Configuration Generator")
        print()
        print("Usage: uv run python mcp-config-generator.py <tool> <method>")
        print()
        print("Available tools:")
        for tool, config in CONFIGS.items():
            methods = ", ".join(config.keys())
            print(f"  {tool}: {methods}")
        print()
        print("Examples:")
        print("  uv run python mcp-config-generator.py cursor local_python")
        print("  uv run python mcp-config-generator.py claude docker")
        print("  uv run python mcp-config-generator.py vscode source")
        return 1

    tool = sys.argv[1].lower()
    method = sys.argv[2].lower()

    return 0 if print_config(tool, method) else 1


if __name__ == "__main__":
    sys.exit(main())
