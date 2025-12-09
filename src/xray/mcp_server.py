import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

"""XRAY MCP Server - Progressive code discovery in 3 steps: Map, Find, Impact.

🚀 THE XRAY WORKFLOW (Progressive Discovery):
1. explore_repo() - Start with directory structure, then zoom in with symbols
2. find_symbol() - Find specific functions/classes you need to analyze  
3. read_interface() - Peek at a file's structure (signatures/docs) without reading implementation
4. what_breaks() - See where that symbol is used (impact analysis)

PROGRESSIVE DISCOVERY EXAMPLE:
```python
# Step 1: Get the lay of the land
tree = explore_repo("/Users/john/myproject")

# Step 2: Find the specific function
symbols = find_symbol("/Users/john/myproject", "validate user")

# Step 3: Check the file interface if unsure
interface = read_interface("/Users/john/myproject", symbols[0]['path'])

# Step 4: See impact
impact = what_breaks(symbols[0])
```

KEY FEATURES:
- Structural Analysis: Uses ast-grep to find ACTUAL code references, ignoring comments/strings.
- Progressive Discovery: Start simple, then add detail.
- Smart Caching: Instant re-runs.
- Stateless: No database to manage.
"""

import os
from typing import Dict, List, Any, Optional, Union

from fastmcp import FastMCP

from xray.core.indexer import XRayIndexer

# Initialize FastMCP server
mcp = FastMCP("XRAY Code Intelligence")

# Cache for indexer instances per repository path
_indexer_cache: Dict[str, XRayIndexer] = {}


def normalize_path(path: str) -> str:
    """Normalize a path to absolute form."""
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    path = str(Path(path).resolve())
    if not os.path.exists(path):
        raise ValueError(f"Path '{path}' does not exist")
    if not os.path.isdir(path):
        raise ValueError(f"Path '{path}' is not a directory")
    return path


def get_indexer(path: str) -> XRayIndexer:
    """Get or create indexer instance for the given path."""
    path = normalize_path(path)
    if path not in _indexer_cache:
        _indexer_cache[path] = XRayIndexer(path)
    return _indexer_cache[path]


@mcp.tool
def explore_repo(
    root_path: str, 
    max_depth: Optional[Union[int, str]] = None,
    include_symbols: Union[bool, str] = False,
    focus_dirs: Optional[List[str]] = None,
    max_symbols_per_file: Union[int, str] = 5
) -> str:
    """
    🗺️ STEP 1: Map the codebase structure - start simple, then zoom in!
    
    PROGRESSIVE DISCOVERY WORKFLOW:
    1. First call: explore_repo("/path/to/project") - See directory structure only
    2. Zoom in: explore_repo("/path/to/project", focus_dirs=["src"], include_symbols=True)
    3. Go deeper: explore_repo("/path/to/project", max_depth=3, include_symbols=True)
    
    INPUTS:
    - root_path: The ABSOLUTE path to the project (e.g., "/Users/john/myproject")
                 NOT relative paths like "./myproject" or "~/myproject"
    - max_depth: How deep to traverse directories (None = unlimited, accepts int or string)
    - include_symbols: Show function/class signatures with docs (False = dirs only, accepts bool or string)
    - focus_dirs: List of top-level directories to focus on (e.g., ["src", "lib"])
    - max_symbols_per_file: Max symbols to show per file when include_symbols=True (accepts int or string)
    
    EXAMPLE 1 - Initial exploration (directory only):
    explore_repo("/Users/john/project")
    # Returns:
    # /Users/john/project/
    # ├── src/
    # ├── tests/
    # ├── docs/
    # └── README.md
    
    EXAMPLE 2 - Zoom into src/ with symbols:
    explore_repo("/Users/john/project", focus_dirs=["src"], include_symbols=True)
    # Returns:
    # /Users/john/project/
    # └── src/
    #     ├── auth.py
    #     │   ├── class AuthService: # Handles user authentication
    #     │   ├── def authenticate(username, password): # Validates credentials
    #     │   └── def logout(session_id): # Ends user session
    #     └── models.py
    #         ├── class User(BaseModel): # User account model
    #         └── ... and 3 more
    
    EXAMPLE 3 - Limited depth exploration:
    explore_repo("/Users/john/project", max_depth=1, include_symbols=True)
    # Shows only top-level dirs and files with their symbols
    
    💡 PRO TIP: Start with include_symbols=False to see structure, then set it to True
    for areas you want to examine in detail. This prevents information overload!
    
    ⚡ PERFORMANCE: Symbol extraction is cached per git commit - subsequent calls are instant!
    
    WHAT TO DO NEXT:
    - If you found interesting directories, zoom in with focus_dirs
    - If you see relevant files, use find_symbol() to locate specific functions
    """
    try:
        # Convert string inputs to proper types (for LLMs that pass strings)
        if max_depth is not None and isinstance(max_depth, str):
            max_depth = int(max_depth)
        if isinstance(max_symbols_per_file, str):
            max_symbols_per_file = int(max_symbols_per_file)
        if isinstance(include_symbols, str):
            include_symbols = include_symbols.lower() in ('true', '1', 'yes')
            
        indexer = get_indexer(root_path)
        tree = indexer.explore_repo(
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file
        )
        return tree
    except Exception as e:
        return f"Error exploring repository: {str(e)}"


@mcp.tool
def find_symbol(root_path: str, query: str) -> List[Dict[str, Any]]:
    """
    🔍 STEP 2: Find specific functions, classes, or methods in the codebase.
    
    USE THIS AFTER explore_repo() when you need to locate a specific piece of code.
    Uses fuzzy matching - you don't need the exact name!
    
    INPUTS:
    - root_path: Same ABSOLUTE path used in explore_repo
    - query: What you're looking for (fuzzy search works!)
             Examples: "auth", "user service", "validate", "parseJSON"
    
    EXAMPLE INPUTS:
    find_symbol("/Users/john/awesome-project", "authenticate")
    find_symbol("/Users/john/awesome-project", "user model")  # Fuzzy matches "UserModel"
    
    EXAMPLE OUTPUT:
    [
        {
            "name": "authenticate_user",
            "type": "function",
            "path": "/Users/john/awesome-project/src/auth.py",
            "start_line": 45,
            "end_line": 67
        },
        {
            "name": "AuthService",
            "type": "class", 
            "path": "/Users/john/awesome-project/src/services.py",
            "start_line": 12,
            "end_line": 89
        }
    ]
    
    RETURNS:
    List of symbol objects (dictionaries). Save these objects - you'll pass them to what_breaks()!
    Empty list if no matches found.
    
    WHAT TO DO NEXT:
    Pick a symbol from the results and pass THE ENTIRE SYMBOL OBJECT to what_breaks() 
    to see where it's used in the codebase.
    """
    try:
        indexer = get_indexer(root_path)
        results = indexer.find_symbol(query)
        return results
    except Exception as e:
        return [{"error": f"Error finding symbol: {str(e)}"}]


@mcp.tool
def read_interface(root_path: str, file_path: str) -> str:
    """
    📖 READ INTERFACE: Get a high-level overview of a file without reading implementation.
    
    Returns function signatures, class definitions, and docstrings.
    Perfect for understanding how to USE a module without reading the whole thing.
    
    INPUTS:
    - root_path: The ABSOLUTE path to the project root
    - file_path: The path to the specific file you want to read (can be relative to root)
    
    EXAMPLE:
    read_interface("/Users/john/project", "src/auth.py")
    """
    try:
        indexer = get_indexer(root_path)
        return indexer.read_interface(file_path)
    except Exception as e:
        return f"Error reading interface: {str(e)}"


@mcp.tool  
def what_breaks(exact_symbol: Dict[str, Any]) -> Dict[str, Any]:
    """
    💥 STEP 3: See what code might break if you change this symbol.
    
    USE THIS AFTER find_symbol() to understand the impact of changing a function/class.
    
    IMPROVEMENTS:
    - Uses structural search (ast-grep) to find ACTUAL code references (ignoring comments/strings).
    - Returns 2 lines of context around each match.
    
    INPUT:
    - exact_symbol: Pass THE ENTIRE SYMBOL OBJECT from find_symbol(), not just the name!
                   Must be a dictionary with AT LEAST 'name' and 'path' keys.
    
    EXAMPLE INPUT:
    # First, get a symbol from find_symbol():
    symbols = find_symbol("/Users/john/project", "authenticate")
    symbol = symbols[0]  # Pick the first result
    
    # Then pass THE WHOLE SYMBOL OBJECT:
    what_breaks(symbol)
    
    EXAMPLE OUTPUT:
    {
        "references": [
            {
                "file": "/Users/john/project/src/api.py",
                "line": 23,
                "text": "    # Authenticate the user\n    user = authenticate_user(username, password)\n    if not user:",
                "type": "code"
            }
        ],
        "total_count": 1,
        "strategy": "structural",
        "note": "Found 1 references using structural search."
    }
    """
    try:
        # Extract root path from the symbol's path
        symbol_path = Path(exact_symbol['path'])
        root_path = str(symbol_path.parent)
        
        # Find a suitable root (go up until we find a git repo or reach root)
        while root_path != '/':
            if (Path(root_path) / '.git').exists():
                break
            parent = Path(root_path).parent
            if parent == Path(root_path):
                break
            root_path = str(parent)
        
        indexer = get_indexer(root_path)
        return indexer.what_breaks(exact_symbol)
    except Exception as e:
        return {"error": f"Error finding references: {str(e)}"}


def main():
    """Main entry point for the XRAY MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()