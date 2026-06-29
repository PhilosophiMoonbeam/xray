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

# Run XRAY directly with uvx
uvx --from . xray explore . --max-depth 2
uvx --from . xray explore . --focus src --include-symbols --format json
uvx --from . xray find . "UserService" --min-score 60

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
xray explore . --max-depth 2
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

# Run the CLI or server
uv run xray explore . --max-depth 2
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

### MCP Tool Discovery

XRAY's MCP server uses a search-first FastMCP surface to keep tool context small.
Most clients initially list only:

- `search_tools` - find XRAY operations by terms such as `map`, `find`, `interface`, or `impact`
- `call_tool` - run the discovered operation with a `{ "name": "...", "arguments": {...} }` payload

The underlying operations are still `explore_repo`, `find_symbol`,
`read_interface`, and `what_breaks`. Longer workflow guidance is available only
when the client asks for it:

- Resource: `xray://workflow`
- Prompt: `xray_discovery_plan`
- Skill: `skill://xray-progressive-discovery/SKILL.md`

FastMCP can generate an ad hoc CLI from this MCP schema, but XRAY intentionally
ships the handwritten `xray` CLI for shell workflows because it exposes direct
map/find/interface/impact commands and stable JSON output.

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

Expected: Impact analysis showing likely symbol-name code references

## Usage Examples

Once configured, use XRAY by adding "use XRAY tools" to your prompts:

```
# Map a codebase
"Map the src/ directory for analysis. use XRAY tools"

# Find symbols
"Find all classes that contain 'User' in their name. use XRAY tools"

# Impact analysis
"What breaks if I change the authenticate method in UserService? use XRAY tools"

# Reference impact
"What code references PaymentProcessor before I change it? use XRAY tools"

# Interface lookup
"Show the interface for src/payments/processor.py before reading implementation. use XRAY tools"
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
   - In MCP clients, start with `search_tools`, then call the selected operation with `call_tool`.
   - `explore_repo` - Visual file tree of your repository
   - `read_interface` - File signatures and docstrings without implementation bodies
   - `find_symbol` - Fuzzy search for functions, classes, and methods
   - `what_breaks` - Find likely symbol-name code references for impact review
   
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
