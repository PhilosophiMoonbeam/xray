#!/bin/bash

if [[ -z "${BASH_SOURCE[0]-}" ]]; then
    echo -e "\033[0;31m❌\033[0m install.sh must be invoked from a local script file" >&2
    exit 2
fi

case "${BASH_SOURCE[0]}" in
    /dev/fd/*|/dev/stdin|/proc/*/fd/*|-)
        echo -e "\033[0;31m❌\033[0m piped and file-descriptor invocations are unsupported" >&2
        exit 2
        ;;
esac

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    echo -e "\033[0;31m❌\033[0m install.sh cannot be sourced" >&2
    return 2 2>/dev/null || exit 2
fi

set -euo pipefail

# XRAY CLI and MCP Installation Script (uv version)
# Usage: bash /path/to/xray/install.sh [--checkout DIRECTORY]

EXPECTED_VERSION="1.0.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    cat <<'EOF'
Usage: bash /path/to/xray/install.sh [--checkout DIRECTORY]

Install XRAY from the local checkout containing this script, or from the
explicitly selected local DIRECTORY.

Options:
  --checkout DIRECTORY  install the explicitly selected local checkout
  --help                show this help
EOF
}

invalid() {
    echo -e "${RED}❌${NC} $*" >&2
    exit 2
}

CHECKOUT_ARGUMENT=""
case "$#" in
    0)
        ;;
    1)
        [[ "$1" == "--help" ]] || invalid "unknown argument: $1"
        usage
        exit 0
        ;;
    2)
        [[ "$1" == "--checkout" ]] || invalid "unknown argument: $1"
        [[ -n "$2" && "$2" != -* ]] || invalid "--checkout requires a directory"
        CHECKOUT_ARGUMENT="$2"
        ;;
    *)
        invalid "expected [--checkout DIRECTORY] or --help"
        ;;
esac

SCRIPT_SOURCE="${BASH_SOURCE[0]}"
[[ -f "$SCRIPT_SOURCE" ]] || invalid "install.sh must be a local regular file"
SCRIPT_PATH=$(readlink -f -- "$SCRIPT_SOURCE") || invalid "cannot resolve install.sh"
[[ -f "$SCRIPT_PATH" ]] || invalid "install.sh must resolve to a local regular file"

if [[ -n "$CHECKOUT_ARGUMENT" ]]; then
    INSTALL_DIR=$(readlink -f -- "$CHECKOUT_ARGUMENT") || invalid "cannot resolve checkout: $CHECKOUT_ARGUMENT"
else
    INSTALL_DIR=$(dirname -- "$SCRIPT_PATH")
fi

[[ -d "$INSTALL_DIR" ]] || invalid "checkout directory does not exist: $INSTALL_DIR"
[[ -f "$INSTALL_DIR/pyproject.toml" ]] || invalid "checkout is missing pyproject.toml: $INSTALL_DIR"
[[ -d "$INSTALL_DIR/src/xray" ]] || invalid "checkout is missing src/xray: $INSTALL_DIR"
grep -Eq '^[[:space:]]*name[[:space:]]*=[[:space:]]*["'\'']xray["'\'']' "$INSTALL_DIR/pyproject.toml" \
    || invalid "checkout pyproject.toml is not an XRAY package: $INSTALL_DIR"

cd -- "$INSTALL_DIR"

echo "🚀 Installing XRAY code intelligence CLI with standard MCP stdio..."

# Check if XRAY is already installed and on the PATH. Source validation above
# deliberately precedes this no-change path.
if command -v xray &>/dev/null; then
    echo -e "${GREEN}✓${NC} XRAY CLI is already installed."
    if [ "${XRAY_INSTALL_FORCE:-}" != "1" ]; then
        if [ -t 0 ]; then
            # Optionally, ask to reinstall for interactive users.
            read -p "Do you want to reinstall? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 0
            fi
        else
            echo "Set XRAY_INSTALL_FORCE=1 to reinstall in non-interactive shells."
            exit 0
        fi
    fi
fi

# Check if uv is installed. This optional prerequisite bootstrap is reached
# only after the local source has been explicitly selected and validated.
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}📦${NC} Installing uv..."

    # Detect OS
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        echo "Please install uv on Windows using:"
        echo "  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\""
        exit 1
    else
        # macOS and Linux
        if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
            echo -e "${RED}❌${NC} Failed to install uv" >&2
            exit 1
        fi

        # Add to PATH for current session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

        # Verify installation
        if command -v uv &> /dev/null; then
            echo -e "${GREEN}✓${NC} uv installed successfully"
        else
            echo -e "${RED}❌${NC} Failed to install uv" >&2
            exit 1
        fi
    fi
else
    echo -e "${GREEN}✓${NC} uv is already installed"
fi

# Do not allow ambient uv project/config selectors to override the explicitly
# selected local checkout.
unset UV_WORKING_DIR UV_PROJECT UV_CONFIG_FILE

# Install XRAY as a uv tool from the absolute selected checkout.
echo -e "${YELLOW}🔧${NC} Installing XRAY with uv..."
if ! uv --no-config --directory "$INSTALL_DIR" tool install --force "$INSTALL_DIR"; then
    echo -e "${RED}❌${NC} Failed to install XRAY with uv" >&2
    exit 1
fi

# Add uv's bin directory to PATH for future sessions.
if ! uv tool update-shell; then
    echo -e "${RED}❌${NC} Failed to update the shell PATH for uv tools" >&2
    exit 1
fi

# Resolve the actual tool directory managed by uv instead of assuming a
# platform-specific path such as ~/.local/bin.
if ! TOOL_BIN_DIR=$(uv --no-config --directory "$INSTALL_DIR" tool dir --bin); then
    echo -e "${RED}❌${NC} Failed to locate the uv tool directory" >&2
    exit 1
fi
[[ -n "$TOOL_BIN_DIR" ]] || {
    echo -e "${RED}❌${NC} uv returned an empty tool directory" >&2
    exit 1
}
[[ -d "$TOOL_BIN_DIR" ]] || {
    echo -e "${RED}❌${NC} uv tool directory does not exist: $TOOL_BIN_DIR" >&2
    exit 1
}
TOOL_BIN_DIR=$(readlink -f -- "$TOOL_BIN_DIR") || {
    echo -e "${RED}❌${NC} cannot resolve the uv tool directory" >&2
    exit 1
}
export PATH="$TOOL_BIN_DIR:$PATH"

XRAY_BIN="$TOOL_BIN_DIR/xray"
MCP_BIN="$TOOL_BIN_DIR/xray-mcp"

# Verify the two entry points directly from uv's selected tool directory.
if [[ ! -x "$XRAY_BIN" ]]; then
    echo -e "${RED}❌${NC} Installation failed: xray CLI is not in the uv tool directory" >&2
    exit 1
fi

if [[ ! -x "$MCP_BIN" ]]; then
    echo -e "${RED}❌${NC} Installation failed: xray-mcp server command is not in the uv tool directory" >&2
    exit 1
fi

if ! INSTALLED_VERSION=$("$XRAY_BIN" --version); then
    echo -e "${RED}❌${NC} Installation failed: xray version check could not run" >&2
    exit 1
fi
if [ "$INSTALLED_VERSION" != "xray $EXPECTED_VERSION" ]; then
    echo -e "${RED}❌${NC} Installation failed: expected xray $EXPECTED_VERSION, got $INSTALLED_VERSION" >&2
    exit 1
fi

# Run verification smoke tests against the selected checkout with the newly
# installed executable, never an unrelated executable earlier on PATH.
echo -e "${YELLOW}🧪${NC} Running installation smoke tests..."
if "$XRAY_BIN" map "$INSTALL_DIR" --depth 1 >/dev/null; then
    echo -e "${GREEN}✓${NC} CLI smoke tests passed"
else
    echo -e "${RED}❌${NC} CLI smoke tests failed" >&2
    exit 1
fi

# Show next steps
echo ""
echo -e "${GREEN}✅ XRAY installed successfully!${NC}"
echo "   $INSTALLED_VERSION"
echo ""
echo "🎯 Quick Start:"
echo "1. Use the agent CLI:"
echo "   xray map /path/to/project --depth 2"
echo "   xray find /path/to/project \"UserService\""
echo ""
echo "2. Optional local/installed MCP stdio config:"
echo '   {"mcpServers": {"xray": {"command": "xray-mcp"}}}'
echo ""
echo "3. Use in prompts:"
echo '   "Analyze this codebase for dependencies. use XRAY tools"'
echo ""
echo "📚 Full documentation:"
echo "   https://github.com/srijanshukla18/xray"
echo ""
echo "💡 Tip: You can also run XRAY without installation using:"
echo "   uvx --from $INSTALL_DIR xray map $INSTALL_DIR --depth 2"
