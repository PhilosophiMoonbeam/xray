#!/bin/bash

# XRAY CLI and MCP Installation Script (uv version)
# Usage: curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "🚀 Installing XRAY code intelligence CLI with MCP compatibility..."

# Check if XRAY is already installed and on the PATH
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

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}📦${NC} Installing uv..."
    
    # Detect OS
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
        echo "Please install uv on Windows using:"
        echo "  powershell -c \"irm https://astral.sh/uv/install.ps1 | iex\""
        exit 1
    else
        # macOS and Linux
        curl -LsSf https://astral.sh/uv/install.sh | sh
        
        # Add to PATH for current session
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        
        # Verify installation
        if command -v uv &> /dev/null; then
            echo -e "${GREEN}✓${NC} uv installed successfully"
        else
            echo -e "${RED}❌${NC} Failed to install uv"
            exit 1
        fi
    fi
else
    echo -e "${GREEN}✓${NC} uv is already installed"
fi

PYTHON_VERSION=$(uv run python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${GREEN}✓${NC} uv Python $PYTHON_VERSION is available"

CURRENT_GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || true)

# Determine installation directory
if [ -n "$CURRENT_GIT_ROOT" ] \
    && [ -f "$CURRENT_GIT_ROOT/pyproject.toml" ] \
    && [ -d "$CURRENT_GIT_ROOT/src/xray" ] \
    && grep -q '^name = "xray"' "$CURRENT_GIT_ROOT/pyproject.toml"; then
    INSTALL_DIR="$CURRENT_GIT_ROOT"
    echo -e "${GREEN}✓${NC} Installing from current XRAY repository: $INSTALL_DIR"
    SKIP_CLONE=true
else
    INSTALL_DIR="$HOME/.xray"
    echo -e "${YELLOW}📦${NC} Installing to default directory: $INSTALL_DIR"
    SKIP_CLONE=false
fi
mkdir -p "$INSTALL_DIR"

# Clone or update XRAY (only if not installing from current repo)
if [ "$SKIP_CLONE" = false ]; then
    echo -e "${YELLOW}📥${NC} Downloading XRAY..."
    if [ -d "$INSTALL_DIR/.git" ]; then
        cd "$INSTALL_DIR"
        echo -e "${YELLOW}🔄${NC} Updating existing installation..."
        if ! git pull origin main; then
            echo -e "${YELLOW}⚠${NC} Git pull failed. Performing clean installation..."
            cd "$HOME"
            rm -rf "$INSTALL_DIR"
            git clone https://github.com/srijanshukla18/xray.git "$INSTALL_DIR"
            cd "$INSTALL_DIR"
        fi
    elif [ -d "$INSTALL_DIR" ]; then
        echo -e "${YELLOW}⚠${NC} Directory exists but is not a git repository. Cleaning up..."
        rm -rf "$INSTALL_DIR"
        git clone https://github.com/srijanshukla18/xray.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    else
        git clone https://github.com/srijanshukla18/xray.git "$INSTALL_DIR"
        cd "$INSTALL_DIR"
    fi
else
    # If installing from current repo, just change to it for uv tool install
    cd "$INSTALL_DIR"
fi

# Install XRAY as a uv tool
echo -e "${YELLOW}🔧${NC} Installing XRAY with uv..."
uv tool install . --force

# Add uv's bin directory to PATH for future sessions
uv tool update-shell

# Ensure the current shell can find the freshly installed binary
export PATH="$HOME/.local/bin:$PATH"

# Verify installation
if ! command -v xray &> /dev/null; then
    echo -e "${RED}❌${NC} Installation failed: xray CLI is not on PATH"
    exit 1
fi

if ! command -v xray-mcp &> /dev/null; then
    echo -e "${RED}❌${NC} Installation failed: xray-mcp compatibility command is not on PATH"
    exit 1
fi

# Run verification smoke tests
echo -e "${YELLOW}🧪${NC} Running installation smoke tests..."
cd "$INSTALL_DIR"
if xray --version >/dev/null && xray map "$INSTALL_DIR" --max-depth 0 >/dev/null; then
    echo -e "${GREEN}✓${NC} CLI smoke tests passed"
else
    echo -e "${RED}❌${NC} CLI smoke tests failed"
    exit 1
fi

# Show next steps
echo ""
echo -e "${GREEN}✅ XRAY installed successfully!${NC}"
echo ""
echo "🎯 Quick Start:"
echo "1. Use the agent CLI:"
echo "   xray map /path/to/project --max-depth 2"
echo "   xray find /path/to/project \"UserService\""
echo ""
echo "2. Optional MCP compatibility config:"
echo '   {"mcpServers": {"xray": {"command": "xray-mcp"}}}'
echo ""
echo "3. Use in prompts:"
echo '   "Analyze this codebase for dependencies. use XRAY tools"'
echo ""
echo "📚 Full documentation:"
echo "   https://github.com/srijanshukla18/xray"
echo ""
echo "💡 Tip: You can also run XRAY without installation using:"
echo "   uvx --from $INSTALL_DIR xray map . --max-depth 2"
