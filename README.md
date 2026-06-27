# XRAY - Agent-Centric Code Intelligence CLI and MCP Server

[![Python](https://img.shields.io/badge/Python-3.10+-green)](https://python.org) [![MCP](https://img.shields.io/badge/MCP-Compatible-purple)](https://modelcontextprotocol.io) [![ast-grep](https://img.shields.io/badge/Powered_by-ast--grep-orange)](https://ast-grep.github.io)

## ❌ Without XRAY

AI assistants struggle with codebase understanding. You get:

- ❌ "I can't see your code structure"
- ❌ "I don't know what depends on this function"
- ❌ Generic refactoring advice without impact analysis
- ❌ No understanding of symbol relationships

## ✅ With XRAY

XRAY gives AI assistants code navigation capabilities through a direct CLI and the existing MCP server. Use the CLI in agent workflows, or add `use XRAY tools` to prompts in MCP-capable assistants:

```txt
Analyze the UserService class and show me what would break if I change the authenticate method. use XRAY tools
```

```txt
Find all functions that call validate_user and show their dependencies. use XRAY tools
```

XRAY provides four focused capabilities:

- 🗺️ **Map** (`xray explore`, `explore_repo`) - See project structure with symbol skeletons
- 🔍 **Find** (`xray find`, `find_symbol`) - Locate functions and classes with fuzzy search
- 📖 **Interface** (`xray interface`, `read_interface`) - Read signatures and docstrings without implementation bodies
- 💥 **Impact** (`xray impact`, `what_breaks`) - Find where a symbol is referenced

## Agent CLI Quick Start

```bash
# Run from a checkout without installing
uvx --from . xray explore . --max-depth 2

# Add source symbols when the agent needs more detail
uvx --from . xray explore . --focus src --include-symbols

# Get a structured repository map for downstream automation
uvx --from . xray explore . --focus src --include-symbols --format json

# Find symbols as scored JSON, filtering weak matches when needed
uvx --from . xray find . "authenticate" --min-score 60

# Inspect a file interface
uvx --from . xray interface . src/xray/core/indexer.py

# Assess impact from a symbol found by `xray find`
symbol=$(uvx --from . xray find . "authenticate" --limit 1 | jq -c '.symbols[0]')
uvx --from . xray impact . --symbol-json "$symbol"
```

JSON output is wrapped in a stable `schema_version: "xray.cli.v1"` envelope with `ok`, `command`, `root_path`, and command-specific data. For example, `xray explore --format json` includes both `tree_text` and structured `entries`; `xray find --format json` includes scored `symbols` with repository-relative `path` and absolute `abs_path`. Manual `xray impact --name ... --path ...` calls require `--start-line` so XRAY can exclude the symbol definition from impact results.

### MCP and Generated CLI

The `xray` command is the supported user-facing CLI. The MCP server is optimized for context economy: clients first see `search_tools` and `call_tool`, then discover `explore_repo`, `find_symbol`, `read_interface`, and `what_breaks` through search. Detailed MCP guidance is available on demand through `xray://workflow`, the `xray_discovery_plan` prompt, and the packaged `skill://xray-progressive-discovery/SKILL.md` skill.

FastMCP's `generate-cli` can generate an ad hoc client from the MCP schema, but XRAY does not ship that generated script as its primary CLI. With the search-first MCP surface, generated commands mirror `search_tools` and `call_tool`; the handwritten `xray` CLI remains clearer for map/find/interface/impact shell workflows and keeps stable JSON envelopes for automation.

## 🚀 Quick Install

### Modern Install with uv (Recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install XRAY
git clone https://github.com/srijanshukla18/xray.git
cd xray
uv tool install .
```

### Automated Install with uv

For the quickest setup, this script automates the `uv` installation process.

```bash
curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash
```

### Generate Config

```bash
# Get config for your tool
uv run python mcp-config-generator.py cursor local_python
uv run python mcp-config-generator.py claude docker
uv run python mcp-config-generator.py vscode source
```

## Language Support

XRAY uses [ast-grep](https://ast-grep.github.io), a tree-sitter powered structural search tool, providing accurate parsing for:
- **Python** - Functions, classes, methods, async functions
- **JavaScript** - Functions, classes, arrow functions, imports
- **TypeScript** - All JavaScript features plus interfaces, type aliases
- **Go** - Functions, structs, interfaces, methods

ast-grep ensures structural accuracy - it understands code syntax, not just text patterns.

## The XRAY Workflow - Progressive Discovery

### 1. Map - Start Simple, Then Zoom In
```python
# First: Get the big picture (directories only)
tree = explore_repo("/path/to/project")
# Returns:
# /path/to/project/
# ├── src/
# ├── tests/
# ├── docs/
# └── config/

# Then: Zoom into areas of interest with full details
tree = explore_repo("/path/to/project", focus_dirs=["src"], include_symbols=True)
# Returns:
# /path/to/project/
# └── src/
#     ├── auth.py
#     │   ├── class AuthService: # Handles user authentication
#     │   ├── def authenticate(username, password): # Validates user credentials
#     │   └── def logout(session_id): # Ends user session
#     └── models.py
#         ├── class User(BaseModel): # User account model
#         └── ... and 3 more

# Or: Limit depth for large codebases
tree = explore_repo("/path/to/project", max_depth=2, include_symbols=True)
```

### 2. Find - Locate Specific Symbols
```python
# Find symbols matching "authenticate" (fuzzy search)
symbols = find_symbol("/path/to/project", "authenticate")
# Returns list of exact symbol objects with name, type, path, line numbers
```

### 3. Impact - See What Would Break
```python
# Find where authenticate_user is used
symbol = symbols[0]  # From find_symbol
result = what_breaks(symbol)
# Returns: {"references": [...], "total_count": 12, 
#          "note": "Found 12 potential references based on text search..."}
```


## Architecture

```
Agent CLI (cli.py) / FastMCP Server (mcp_server.py)
    ↓
Core Engine (src/xray/core/)
    └── indexer.py      # Orchestrates ast-grep for structural analysis
    ↓
ast-grep (external binary)
    └── Tree-sitter powered structural search
```

**Stateless design** - No database, no persistent index. Each operation runs fresh ast-grep queries for real-time accuracy.

## Why ast-grep?

Traditional grep searches text. ast-grep searches code structure:

- **grep**: Finds "authenticate" in function names, variables, comments, strings
- **ast-grep**: Finds only `def authenticate()` or `function authenticate()` definitions

This structural approach provides clean, accurate results essential for reliable code intelligence.

## Performance Characteristics

- **Startup**: Fast - launches ast-grep subprocess
- **File tree**: Python directory traversal
- **Symbol search**: Runs multiple ast-grep patterns, speed depends on codebase size
- **Impact analysis**: Name-based search across all files
- **Memory**: Minimal - no persistent state

## What Makes This Practical

1. **Progressive Discovery** - Start with directories, add symbols only where needed
2. **Smart Caching** - Symbol extraction cached per git commit for instant re-runs
3. **Flexible Focus** - Use `focus_dirs` to zoom into specific parts of large codebases
4. **Enhanced Symbols** - See function signatures and docstrings, not just names
5. **Based on tree-sitter** - ast-grep provides accurate structural analysis

XRAY helps AI assistants avoid information overload while providing deep code intelligence where needed.

## Stateless Design

XRAY performs on-demand structural analysis using ast-grep. There's no database to manage, no index to build, and no state to maintain. Each query runs fresh against your current code.

## Getting Started

1. **Install**: See [`getting_started.md`](getting_started.md) for modern installation
2. **Map the terrain**: `explore_repo("/path/to/project")`
3. **Find your target**: `find_symbol("/path/to/project", "UserService")`
4. **Assess impact**: `what_breaks(symbol)`

## The XRAY Philosophy

XRAY bridges the gap between simple text search and complex LSP servers:

- **More than grep** - Matches code syntax patterns, not just text
- **Less than LSP** - No language servers or complex setup
- **Practical for AI** - Provides structured data about code relationships

A simple tool that helps AI assistants navigate codebases more effectively than text search alone.

## Architectural Journey & Design Rationale

The current implementation of XRAY is the result of a rigorous evaluation of multiple code analysis methodologies. My journey involved prototyping and assessing several distinct approaches, each with its own set of trade-offs. Below is a summary of the considered architectures and the rationale for my final decision.

1.  **Naive Grep-Based Analysis**: I initially explored a baseline approach using standard `grep` for symbol identification. While expedient, this method proved fundamentally inadequate due to its inability to differentiate between syntactical constructs and simple text occurrences (e.g., comments, strings, variable names). The high signal-to-noise ratio rendered it impractical for reliable code intelligence.

2.  **Tree-Sitter Native Integration**: A direct integration with `tree-sitter` was evaluated to leverage its powerful parsing capabilities. However, this path was fraught with significant implementation complexities, including intractable errors within the parser generation and binding layers. The maintenance overhead and steep learning curve for custom grammar development were deemed prohibitive for a lean, multi-language tool.

3.  **Language Server Protocol (LSP)**: I considered leveraging the Language Server Protocol for its comprehensive, standardized approach to code analysis. This was ultimately rejected due to the excessive operational burden it would impose on the end-user, requiring them to install, configure, and manage separate LSPs for each language in their environment. This friction conflicted with my goal of a lightweight, zero-configuration user experience.

4.  **Comby-Based Structural Search**: `Comby` was explored for its structural search and replacement capabilities. Despite its promising feature set, I encountered significant runtime instability and idiosyncratic behavior that undermined its reliability for mission-critical code analysis. The tool's performance and consistency did not meet my stringent requirements for a production-ready system.

5.  **ast-grep as the Core Engine**: My final and current architecture is centered on `ast-grep`. This tool provides the optimal balance of structural awareness, performance, and ease of integration. By leveraging `tree-sitter` internally, it offers robust, syntactically-aware code analysis without the complexities of direct `tree-sitter` integration or the overhead of LSPs. Its reliability and rich feature set for structural querying made it the unequivocal choice for XRAY's core engine.

---

# Getting Started with XRAY - Modern Installation with uv

XRAY is a minimal-dependency code intelligence system that enhances AI assistants' understanding of codebases. This guide shows how to install and use XRAY with the modern `uv` package manager.

## Prerequisites

- Python 3.10 or later
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager

### Installing uv

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or with pip
pip install uv
```

## Installation Options

### Option 1: Automated Install (Easiest)

For the quickest setup, use the one-line installer from the `README.md`. This will handle everything for you.

```bash
curl -fsSL https://raw.githubusercontent.com/srijanshukla18/xray/main/install.sh | bash
```

### Option 2: Quick Try with uvx (Recommended for Testing)

Run XRAY directly without installation using `uvx`:

```bash
# Clone the repository
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Run the CLI directly with uvx
uvx --from . xray map . --max-depth 2

# Or run the MCP server
uvx --from . xray-mcp
```

### Option 3: Install as a Tool (Recommended for Regular Use)

Install XRAY as a persistent tool:

```bash
# Clone and install
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Install with uv
uv tool install .

# Now you can run xray and xray-mcp from anywhere
xray map . --max-depth 2
xray-mcp
```

### Option 4: Development Installation

For contributing or modifying XRAY:

```bash
# Clone the repository
git clone https://github.com/srijanshukla18/xray.git
cd xray

# Create and activate virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode
uv pip install -e .

# Run the CLI or MCP server
uv run xray map . --max-depth 2
uv run xray-mcp
```

## Configure Your AI Assistant

After installation, configure your AI assistant to use XRAY:

### Using the MCP Config Generator (Recommended)

For easier configuration, use the `mcp-config-generator.py` script located in the XRAY repository. This script can generate the correct JSON configuration for various AI assistants and installation methods.

To use it:

1.  Navigate to the XRAY repository root:
    ```bash
    cd /path/to/xray
    ```
2.  Run the script with your desired tool and installation method. For example, to get the configuration for Claude Desktop with an installed `xray-mcp` script:
    ```bash
    uv run python mcp-config-generator.py claude installed_script
    ```
    Or for VS Code with a local Python installation:
    ```bash
    uv run python mcp-config-generator.py vscode local_python
    ```
    The script will print the JSON configuration and instructions on where to add it.

    Available tools: `cursor`, `claude`, `vscode`
    Available methods: `local_python`, `docker`, `source`, `installed_script` (method availability varies by tool)

### Manual Configuration (Advanced)

If you prefer to configure manually, here are examples for common AI assistants:

#### Claude CLI (Claude Code)

For Claude CLI users, simply run:

```bash
claude mcp add xray xray-mcp -s local
```

Then verify it's connected:

```bash
claude mcp list | grep xray
```

#### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "xray": {
      "command": "uvx",
      "args": ["--from", "/path/to/xray", "xray-mcp"]
    }
  }
}
```

Or if installed as a tool:

```json
{
  "mcpServers": {
    "xray": {
      "command": "xray-mcp"
    }
  }
}
```

#### Cursor

Settings → Cursor Settings → MCP → Add new global MCP server:

```json
{
  "mcpServers": {
    "xray": {
      "command": "xray-mcp"
    }
  }
}
```

## Minimal Dependencies

One of XRAY's best features is its minimal dependency profile. You don't need to install a suite of language servers. XRAY uses:

- **ast-grep**: A single, fast binary for structural code analysis.
- **Python**: For the server and core logic.

This means you can start using XRAY immediately after installation with no complex setup!

## Verify Installation

### 1. Check XRAY is accessible

```bash
# If installed as tool
xray --version

# If using uvx
uvx --from /path/to/xray xray --version
```

### 2. Test basic functionality

Create a test file `test_xray.py`:

```python
def hello_world():
    print("Hello from XRAY test!")

def calculate_sum(a, b):
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
```

### 3. In your AI assistant, test these commands:

```
Map the current directory. use XRAY tools
```

Expected: Repository tree output

```
Find all functions containing "hello". use XRAY tools
```

Expected: Should find `hello_world` function

```
What would break if I change the multiply method? use XRAY tools
```

Expected: Impact analysis showing any dependencies

## Usage Examples

Once configured, use XRAY by adding "use XRAY tools" to your prompts:

```
# Map a codebase
"Map the src/ directory for analysis. use XRAY tools"

# Find symbols
"Find all classes that contain 'User' in their name. use XRAY tools"

# Impact analysis
"What breaks if I change the authenticate method in UserService? use XRAY tools"

# Dependency tracking
"What does the PaymentProcessor class depend on? use XRAY tools"

# Location queries
"What function is defined at line 125 in main.py? use XRAY tools"
```

## Troubleshooting

### uv not found

Make sure uv is in your PATH:

```bash
# Add to ~/.bashrc or ~/.zshrc
export PATH="$HOME/.cargo/bin:$PATH"
```

### Permission denied

On macOS/Linux, you might need to make the script executable:

```bash
chmod +x ~/.local/bin/xray-mcp
```

### Python version issues

XRAY requires Python 3.10+. Check your version:

```bash
uv run python --version

# If needed, install Python 3.10+ with uv
uv python install 3.10
```

### MCP connection issues

1. Check the CLI path: `xray map . --max-depth 1`
2. Verify your MCP config JSON is valid
3. Restart your AI assistant after config changes

## Runtime Model

XRAY is stateless. It runs on-demand analysis against the repository path you pass to the CLI or MCP tool, uses `ast-grep` for structural search, and does not require a database service or persistent project index.

## What's Next?

1. **Map your first repository**: In your AI assistant, ask it to "Map my project. use XRAY tools"

2. **Explore the tools**:
   - `explore_repo` - Visual file tree of your repository
   - `read_interface` - File signatures and docstrings without implementation bodies
   - `find_symbol` - Fuzzy search for functions, classes, and methods
   - `what_breaks` - Find what code depends on a symbol (reverse dependencies)
   
   Note: Results may include matches from comments or strings. The AI assistant will intelligently filter based on context.

3. **Read the documentation**: Check out the [README](README.md) for detailed examples and API reference

## Why XRAY Uses a Minimal Dependency Approach

XRAY is designed for simplicity and ease of use. It relies on:

- **ast-grep**: A powerful and fast single-binary tool for code analysis.
- **Python**: For its robust standard library and ease of scripting.

This approach avoids the complexity of setting up and managing multiple language servers, while still providing accurate, structural code intelligence.

## Benefits of Using uv

- **10-100x faster** than pip for installations
- **No virtual environment hassles** - uv manages everything
- **Reproducible installs** - supports lockfiles when an application wants pinned environments
- **Built-in Python management** - install any Python version
- **Global tool management** - like pipx but faster

Happy coding with XRAY! 🚀
