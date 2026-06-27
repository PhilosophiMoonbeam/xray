"""Core indexing engine for XRAY - ast-grep based implementation."""

import os
import re
import ast
import json
import subprocess
import hashlib
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Any, Set, Tuple
import fnmatch
from thefuzz import fuzz

# Default exclusions
DEFAULT_EXCLUSIONS = {
    # Directories
    "node_modules", "vendor", "__pycache__", "venv", ".venv", "env",
    "target", "build", "dist", ".git", ".svn", ".hg", ".idea", ".vscode",
    ".xray", "site-packages", ".tox", ".pytest_cache", ".mypy_cache",
    
    # File patterns
    "*.pyc", "*.pyo", "*.pyd", "*.so", "*.dll", "*.log", 
    ".DS_Store", "Thumbs.db", "*.swp", "*.swo", "*~"
}

# Language extensions
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript", 
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
}


class XRayIndexer:
    """Main indexer for XRAY - provides file tree and symbol extraction using ast-grep."""
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self._cache = {}
        self.last_warnings: List[str] = []
        self._init_cache()
    
    def _init_cache(self):
        """Initialize cache based on git commit SHA."""
        try:
            # Get current git commit SHA
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.root_path,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.commit_sha = result.stdout.strip()
                self.cache_dir = Path(f"/tmp/.xray_cache/{self.commit_sha}")
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                self._load_cache()
            else:
                self.commit_sha = None
                self.cache_dir = None
        except:
            self.commit_sha = None
            self.cache_dir = None
    
    def _load_cache(self):
        """Load cache from disk if available."""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "symbols.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, 'rb') as f:
                    self._cache = pickle.load(f)
            except:
                self._cache = {}
    
    def _save_cache(self):
        """Save cache to disk."""
        if not self.cache_dir:
            return
        
        cache_file = self.cache_dir / "symbols.pkl"
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(self._cache, f)
        except:
            pass
    
    def _get_cache_key(self, file_path: Path) -> str:
        """Generate cache key for a file."""
        try:
            stat = file_path.stat()
            return f"{file_path}:{stat.st_mtime}:{stat.st_size}"
        except:
            return str(file_path)
    
    def explore_repo(
        self, 
        max_depth: Optional[int] = None,
        include_symbols: bool = False,
        focus_dirs: Optional[List[str]] = None,
        max_symbols_per_file: int = 5
    ) -> str:
        """
        Build a visual file tree with optional symbol skeletons.
        
        Args:
            max_depth: Limit directory traversal depth
            include_symbols: Include symbol skeletons in output
            focus_dirs: Only include these top-level directories
            max_symbols_per_file: Max symbols to show per file
            
        Returns:
            Formatted tree string
        """
        # Get gitignore patterns if available
        gitignore_patterns = self._parse_gitignore()
        
        # Build the tree
        tree_lines = []
        self._build_tree_recursive_enhanced(
            self.root_path, 
            tree_lines, 
            "", 
            gitignore_patterns,
            current_depth=0,
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file,
            is_last=True
        )
        
        # Save cache after building tree
        if include_symbols:
            self._save_cache()
        
        return "\n".join(tree_lines)

    def explore_repo_data(
        self,
        max_depth: Optional[int] = None,
        include_symbols: bool = False,
        focus_dirs: Optional[List[str]] = None,
        max_symbols_per_file: int = 5
    ) -> Dict[str, Any]:
        """
        Build structured repository map data for CLI and automation.

        The text tree remains available through explore_repo for MCP compatibility.
        """
        gitignore_patterns = self._parse_gitignore()
        entries: List[Dict[str, Any]] = []
        self._collect_tree_entries(
            self.root_path,
            entries,
            gitignore_patterns,
            current_depth=0,
            max_depth=max_depth,
            include_symbols=include_symbols,
            focus_dirs=focus_dirs,
            max_symbols_per_file=max_symbols_per_file
        )

        if include_symbols:
            self._save_cache()

        return {
            "root_path": str(self.root_path),
            "entries": entries,
            "options": {
                "max_depth": max_depth,
                "include_symbols": include_symbols,
                "focus_dirs": focus_dirs or [],
                "max_symbols_per_file": max_symbols_per_file,
            },
        }
    
    def _parse_gitignore(self) -> Set[str]:
        """Parse .gitignore file if it exists."""
        patterns = set()
        gitignore_path = self.root_path / ".gitignore"
        
        if gitignore_path.exists():
            try:
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            patterns.add(line)
            except Exception:
                pass
        
        return patterns
    
    def _should_exclude(self, path: Path, gitignore_patterns: Set[str]) -> bool:
        """Check if a path should be excluded."""
        name = path.name

        if path != self.root_path and not self._is_inside_root(path):
            return True

        # Avoid following symlinked directories, which can escape the root or cycle.
        if path.is_symlink() and path.is_dir():
            return True
        
        # Check default exclusions
        if name in DEFAULT_EXCLUSIONS:
            return True
        
        # Check file pattern exclusions
        for pattern in DEFAULT_EXCLUSIONS:
            if '*' in pattern and fnmatch.fnmatch(name, pattern):
                return True
        
        # Check gitignore patterns (simplified)
        for pattern in gitignore_patterns:
            if pattern in str(path.relative_to(self.root_path)):
                return True
            if fnmatch.fnmatch(name, pattern):
                return True
        
        return False

    def _is_inside_root(self, path: Path) -> bool:
        """Return whether a path resolves inside the repository root."""
        try:
            path.resolve().relative_to(self.root_path)
            return True
        except ValueError:
            return False
    
    def _should_include_dir(self, path: Path, focus_dirs: Optional[List[str]], current_depth: int) -> bool:
        """Check if a directory should be included based on focus_dirs."""
        if not focus_dirs or current_depth > 0:
            return True
        if path == self.root_path:
            return True
        
        # At depth 0 (top-level), only include if in focus_dirs
        return path.name in focus_dirs

    def _collect_tree_entries(
        self,
        path: Path,
        entries: List[Dict[str, Any]],
        gitignore_patterns: Set[str],
        current_depth: int,
        max_depth: Optional[int],
        include_symbols: bool,
        focus_dirs: Optional[List[str]],
        max_symbols_per_file: int
    ):
        """Collect a flat, structured repository map."""
        if self._should_exclude(path, gitignore_patterns):
            return

        if max_depth is not None and current_depth > max_depth:
            return

        if path.is_dir() and not self._should_include_dir(path, focus_dirs, current_depth):
            return

        try:
            relative_path = "." if path == self.root_path else path.relative_to(self.root_path).as_posix()
        except ValueError:
            relative_path = str(path)

        entry: Dict[str, Any] = {
            "path": relative_path,
            "abs_path": str(path),
            "name": path.name if path != self.root_path else self.root_path.name,
            "kind": "directory" if path.is_dir() else "file",
            "depth": current_depth,
        }

        language = LANGUAGE_MAP.get(path.suffix.lower()) if path.is_file() else None
        if language:
            entry["language"] = language

        if path.is_file() and include_symbols and language:
            entry["symbols"] = self._get_file_symbol_data(path, max_symbols_per_file)

        entries.append(entry)

        if not path.is_dir():
            return

        try:
            children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            children = [c for c in children if not self._should_exclude(c, gitignore_patterns)]

            if current_depth == 0 and focus_dirs:
                children = [c for c in children if c.is_file() or c.name in focus_dirs]

            for child in children:
                self._collect_tree_entries(
                    child,
                    entries,
                    gitignore_patterns,
                    current_depth + 1,
                    max_depth,
                    include_symbols,
                    focus_dirs,
                    max_symbols_per_file
                )
        except PermissionError:
            pass

    def _get_file_symbol_data(self, file_path: Path, max_symbols: int) -> List[Dict[str, str]]:
        """Return structured symbol skeleton data for a source file."""
        cache_key = self._get_cache_key(file_path)
        if cache_key not in self._cache:
            self._get_file_skeleton_enhanced(file_path, max_symbols)

        symbols = self._cache.get(cache_key, [])
        structured_symbols = []
        for symbol in symbols[:max_symbols]:
            signature = symbol.get("signature", "")
            structured_symbols.append({
                "name": self._extract_symbol_name(signature) or signature,
                "type": self._infer_symbol_type(signature),
                "signature": signature,
                "doc": symbol.get("doc", ""),
            })

        if len(symbols) > max_symbols:
            structured_symbols.append({
                "name": "...",
                "type": "truncated",
                "signature": f"... and {len(symbols) - max_symbols} more",
                "doc": "",
            })

        return structured_symbols

    def _infer_symbol_type(self, signature: str) -> str:
        """Infer a symbol type from a skeleton signature."""
        if signature.startswith("class "):
            return "class"
        if signature.startswith(("def ", "async def ", "function ", "const ", "let ", "var ")):
            return "function"
        if signature.startswith("func "):
            return "function"
        if signature.startswith("type ") and " struct" in signature:
            return "struct"
        if signature.startswith("type ") and " interface" in signature:
            return "interface"
        return "symbol"
    
    def _build_tree_recursive_enhanced(
        self, 
        path: Path, 
        tree_lines: List[str], 
        prefix: str, 
        gitignore_patterns: Set[str],
        current_depth: int,
        max_depth: Optional[int],
        include_symbols: bool,
        focus_dirs: Optional[List[str]],
        max_symbols_per_file: int,
        is_last: bool = False
    ):
        """Recursively build the tree representation with enhanced features."""
        if self._should_exclude(path, gitignore_patterns):
            return
        
        # Check depth limit
        if max_depth is not None and current_depth > max_depth:
            return
        
        # Check focus_dirs for directories
        if path.is_dir() and not self._should_include_dir(path, focus_dirs, current_depth):
            return
        
        # Add current item
        name = path.name if path != self.root_path else str(path)
        connector = "└── " if is_last else "├── "
        
        # For files, add skeleton if requested
        if path.is_file() and include_symbols and path.suffix.lower() in LANGUAGE_MAP:
            skeleton = self._get_file_skeleton_enhanced(path, max_symbols_per_file)
            if skeleton:
                # Format with indented skeleton
                if path == self.root_path:
                    tree_lines.append(name)
                else:
                    tree_lines.append(prefix + connector + name)
                
                # Add skeleton lines
                for i, skel_line in enumerate(skeleton):
                    is_last_skel = (i == len(skeleton) - 1)
                    skel_prefix = prefix + ("    " if is_last else "│   ")
                    skel_connector = "└── " if is_last_skel else "├── "
                    tree_lines.append(skel_prefix + skel_connector + skel_line)
            else:
                # No skeleton, just show filename
                if path == self.root_path:
                    tree_lines.append(name)
                else:
                    tree_lines.append(prefix + connector + name)
        else:
            # Directory or file without symbols
            if path == self.root_path:
                tree_lines.append(name)
            else:
                tree_lines.append(prefix + connector + name)
        
        # Only recurse into directories
        if path.is_dir():
            # Get children and sort them
            try:
                children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                # Filter out excluded items
                children = [c for c in children if not self._should_exclude(c, gitignore_patterns)]
                
                # Apply focus_dirs filter at top level
                if current_depth == 0 and focus_dirs:
                    children = [c for c in children if c.is_file() or c.name in focus_dirs]
                
                for i, child in enumerate(children):
                    is_last_child = (i == len(children) - 1)
                    extension = "    " if is_last else "│   "
                    new_prefix = prefix + extension if path != self.root_path else ""
                    
                    self._build_tree_recursive_enhanced(
                        child, 
                        tree_lines, 
                        new_prefix, 
                        gitignore_patterns,
                        current_depth + 1,
                        max_depth,
                        include_symbols,
                        focus_dirs,
                        max_symbols_per_file,
                        is_last_child
                    )
            except PermissionError:
                pass
    
    def read_interface(self, file_path: str) -> str:
        """
        Read the interface (skeleton) of a specific file.
        Returns function signatures, class definitions, and types, but hides implementation details.
        """
        try:
            target_path = self._resolve_file_inside_root(file_path)

            if not target_path.exists() or not target_path.is_file():
                return f"Error: File '{file_path}' not found or is not a file."
            
            # Use the existing skeleton logic, but with a high limit on symbols
            skeleton = self._get_file_skeleton_enhanced(target_path, max_symbols=1000)
            
            if not skeleton:
                # Fallback: if no symbols found or language not supported, 
                # maybe just read the first few lines? or return message?
                language = LANGUAGE_MAP.get(target_path.suffix.lower())
                if not language:
                    return f"File type '{target_path.suffix}' not supported for interface extraction."
                return "No symbols found in file."
                
            return "\n".join(skeleton)
            
        except Exception as e:
            return f"Error reading interface: {str(e)}"

    def _resolve_file_inside_root(self, file_path: str) -> Path:
        """Resolve a file path and require it to remain inside the repository root."""
        target_path = Path(file_path).expanduser()
        if not target_path.is_absolute():
            target_path = self.root_path / target_path

        target_path = target_path.resolve()
        try:
            target_path.relative_to(self.root_path)
        except ValueError:
            raise ValueError(f"File '{file_path}' is outside repository root '{self.root_path}'.")

        return target_path

    def _get_file_skeleton_enhanced(self, file_path: Path, max_symbols: int) -> List[str]:
        """Extract enhanced symbol info including signatures and docstrings."""
        # Check cache first
        cache_key = self._get_cache_key(file_path)
        if cache_key in self._cache:
            cached_symbols = self._cache[cache_key]
            return self._format_enhanced_skeleton(cached_symbols, max_symbols)
        
        language = LANGUAGE_MAP.get(file_path.suffix.lower())
        if not language:
            return []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if language == "python":
                symbols = self._extract_python_symbols_enhanced(content)
            else:
                symbols = self._extract_regex_symbols_enhanced(content, language)
            
            # Cache the results
            self._cache[cache_key] = symbols
            
            return self._format_enhanced_skeleton(symbols, max_symbols)
        
        except Exception:
            return []
    
    def _format_enhanced_skeleton(self, symbols: List[Dict[str, str]], max_symbols: int) -> List[str]:
        """Format enhanced symbol info for display."""
        if not symbols:
            return []
        
        lines = []
        shown_count = min(len(symbols), max_symbols)
        
        for symbol in symbols[:shown_count]:
            line = symbol['signature']
            if symbol.get('doc'):
                line += f" # {symbol['doc']}"
            lines.append(line)
        
        if len(symbols) > max_symbols:
            remaining = len(symbols) - max_symbols
            lines.append(f"... and {remaining} more")
        
        return lines
    
    def _extract_python_symbols_enhanced(self, content: str) -> List[Dict[str, str]]:
        """Extract Python symbols with signatures and docstrings."""
        symbols = []
        try:
            tree = ast.parse(content)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.ClassDef):
                    sig = f"class {node.name}"
                    if node.bases:
                        base_names = []
                        for base in node.bases:
                            if isinstance(base, ast.Name):
                                base_names.append(base.id)
                            elif isinstance(base, ast.Attribute):
                                base_names.append(ast.unparse(base))
                        if base_names:
                            sig += f"({', '.join(base_names)})"
                    sig += ":"
                    
                    doc = ast.get_docstring(node)
                    if doc:
                        doc = doc.split('\n')[0].strip()[:50]
                    
                    symbols.append({'signature': sig, 'doc': doc or ''})
                    
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Build function signature
                    sig = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                    sig += f"{node.name}("
                    
                    # Add parameters
                    args = []
                    for arg in node.args.args:
                        args.append(arg.arg)
                    if args:
                        sig += ", ".join(args)
                    sig += "):"
                    
                    doc = ast.get_docstring(node)
                    if doc:
                        doc = doc.split('\n')[0].strip()[:50]
                    
                    symbols.append({'signature': sig, 'doc': doc or ''})
        except:
            pass
        return symbols
    
    def _extract_regex_symbols_enhanced(self, content: str, language: str) -> List[Dict[str, str]]:
        """Extract symbols with signatures and comments for JS/TS/Go."""
        symbols = []
        
        # Language-specific patterns
        if language in ["javascript", "typescript"]:
            patterns = [
                # Function with preceding comment
                (r'(?://\s*(.+?)\n)?^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\((.*?)\)', 
                 lambda m: {'signature': f"function {m.group(2)}({m.group(3)}):", 'doc': (m.group(1) or '').strip()}),
                
                # Class with preceding comment
                (r'(?://\s*(.+?)\n)?^\s*(?:export\s+)?class\s+(\w+)(?:\s+extends\s+(\w+))?', 
                 lambda m: {'signature': f"class {m.group(2)}" + (f" extends {m.group(3)}" if m.group(3) else "") + ":", 
                           'doc': (m.group(1) or '').strip()}),
                
                # Arrow function with const
                (r'(?://\s*(.+?)\n)?^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\((.*?)\)\s*=>', 
                 lambda m: {'signature': f"const {m.group(2)} = ({m.group(3)}) =>", 'doc': (m.group(1) or '').strip()}),
            ]
        elif language == "go":
            patterns = [
                # Function with preceding comment
                (r'(?://\s*(.+?)\n)?^func\s+(\w+)\s*\((.*?)\)', 
                 lambda m: {'signature': f"func {m.group(2)}({m.group(3)})", 'doc': (m.group(1) or '').strip()}),
                
                # Method with preceding comment
                (r'(?://\s*(.+?)\n)?^func\s*\((\w+\s+[*]?\w+)\)\s*(\w+)\s*\((.*?)\)', 
                 lambda m: {'signature': f"func ({m.group(2)}) {m.group(3)}({m.group(4)})", 
                           'doc': (m.group(1) or '').strip()}),
                
                # Type struct with preceding comment
                (r'(?://\s*(.+?)\n)?^type\s+(\w+)\s+struct', 
                 lambda m: {'signature': f"type {m.group(2)} struct", 'doc': (m.group(1) or '').strip()}),
            ]
        else:
            return symbols
        
        # Apply patterns
        for pattern, extractor in patterns:
            for match in re.finditer(pattern, content, re.MULTILINE):
                symbols.append(extractor(match))
        
        return symbols
    
    def find_symbol(
        self,
        query: str,
        limit: int = 10,
        min_score: int = 0,
        include_scores: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Find symbols matching the query using fuzzy search.
        Uses ast-grep to find all symbols, then fuzzy matches against the query.
        
        Returns a list of the top matching "Exact Symbol" objects.
        """
        all_symbols = []
        self.last_warnings = []
        self.last_search_succeeded = False
        
        # Define patterns for different symbol types
        patterns = [
            # Python functions and classes
            ("def $NAME($$$)", "function"),
            ("class $NAME: $$$", "class"),
            ("class $NAME($$$): $$$", "class"),
            
            # JavaScript/TypeScript functions and classes
            ("function $NAME($$$)", "function"),
            ("const $NAME = ($$$) =>", "function"),
            ("let $NAME = ($$$) =>", "function"),
            ("var $NAME = ($$$) =>", "function"),
            ("class $NAME", "class"),
            ("interface $NAME", "interface"),
            ("type $NAME =", "type"),
            
            # Go functions and types
            ("func $NAME($$$)", "function"),
            ("func ($$$) $NAME($$$)", "method"),
            ("type $NAME struct", "struct"),
            ("type $NAME interface", "interface"),
        ]
        
        # Run ast-grep for each pattern
        for pattern, symbol_type in patterns:
            cmd = [
                "ast-grep",
                "run",
                "--pattern", pattern,
                "--json",
                str(self.root_path)
            ]
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                self.last_warnings.append("ast-grep executable was not found; symbol search could not run.")
                break
            
            if result.returncode == 0:
                self.last_search_succeeded = True
                try:
                    matches = json.loads(result.stdout)
                    for match in matches:
                        # Extract details from match
                        text = match.get("text", "")
                        file_path = match.get("file", "")
                        start = match.get("range", {}).get("start", {})
                        end = match.get("range", {}).get("end", {})
                        
                        # Extract the name from metavariables
                        metavars = match.get("metaVariables", {})
                        name = None
                        
                        # Try to get NAME from metavariables
                        name_var = self._get_metavariable(metavars, "NAME")
                        if name_var:
                            name = name_var.get("text")
                        else:
                            # Fallback to regex extraction
                            name = self._extract_symbol_name(text)
                        
                        if name:
                            symbol = {
                                "name": name,
                                "type": symbol_type,
                                "path": file_path,
                                "start_line": self._normalize_ast_grep_line(start.get("line")),
                                "end_line": self._normalize_ast_grep_line(end.get("line", start.get("line")))
                            }
                            all_symbols.append(symbol)
                except json.JSONDecodeError:
                    self.last_warnings.append(f"ast-grep returned invalid JSON for pattern {pattern!r}.")
            else:
                stderr = result.stderr.strip()
                detail = f": {stderr}" if stderr else ""
                self.last_warnings.append(f"ast-grep failed for pattern {pattern!r}{detail}")
        
        # Deduplicate symbols (same name and location)
        seen = set()
        unique_symbols = []
        for symbol in all_symbols:
            key = (symbol["name"], symbol["path"], symbol["start_line"])
            if key not in seen:
                seen.add(key)
                unique_symbols.append(symbol)
        
        # Now perform fuzzy matching against the query
        scored_symbols = []
        for symbol in unique_symbols:
            # Calculate similarity score
            score = fuzz.partial_ratio(query.lower(), symbol["name"].lower())
            
            # Boost score for exact substring matches
            if query.lower() in symbol["name"].lower():
                score = max(score, 80)
            
            if score >= min_score:
                scored_symbols.append((score, symbol))
        
        # Sort by score and take top results
        scored_symbols.sort(key=lambda x: x[0], reverse=True)
        if include_scores:
            top_symbols = []
            for score, symbol in scored_symbols[:limit]:
                scored_symbol = dict(symbol)
                scored_symbol["score"] = score
                top_symbols.append(scored_symbol)
        else:
            top_symbols = [s[1] for s in scored_symbols[:limit]]
        
        return top_symbols

    def _get_metavariable(self, metavars: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
        """Return a metavariable from old or current ast-grep JSON shapes."""
        if name in metavars:
            value = metavars[name]
            if isinstance(value, dict):
                return value

        single_vars = metavars.get("single", {})
        if isinstance(single_vars, dict):
            value = single_vars.get(name)
            if isinstance(value, dict):
                return value

        return None

    def _normalize_ast_grep_line(self, line: Optional[int]) -> int:
        """Convert ast-grep zero-based line values to one-based line numbers."""
        if line is None:
            return 1
        return int(line) + 1
    
    def _extract_symbol_name(self, text: str) -> Optional[str]:
        """Extract the symbol name from matched text."""
        # Patterns to extract names from different definition types
        patterns = [
            r'(?:def|class|function|interface|type)\s+(\w+)',
            r'(?:const|let|var)\s+(\w+)\s*=',
            r'func\s+(?:\([^)]+\)\s+)?(\w+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        return None
    
    def what_breaks(self, exact_symbol: Dict[str, Any], context_lines: int = 2) -> Dict[str, Any]:
        """
        Find what uses a symbol (reverse dependencies) using structural search.
        Prioritizes ast-grep for code references, falls back to text search.
        """
        symbol_name = exact_symbol['name']
        definition_path_value = exact_symbol.get('abs_path') or exact_symbol['path']
        definition_path = str(Path(definition_path_value).resolve())
        definition_start = exact_symbol.get('start_line', -1)
        
        references = []
        strategy = "structural"
        
        # Try structural search first (ast-grep)
        struct_refs = self._ast_grep_search(symbol_name, context_lines)
        
        if struct_refs:
            # Filter out the definition itself
            for ref in struct_refs:
                ref_path = str(Path(ref['file']).resolve())
                ref_line = ref['line']
                
                # Simple collision check: same file and line is close to definition
                # (ast-grep definition match might be on definition line)
                if ref_path == definition_path and abs(ref_line - definition_start) <= 1:
                    continue
                    
                references.append(ref)
        else:
            # Fallback to text search if ast-grep found nothing (or failed)
            # Note: This might happen if the symbol is not in a supported language file
            # or if it's only used in comments/strings (which we might want to know about as fallback?)
            # For now, if structural search returns empty list, we trust it for code.
            # But we might want to run text search as a backup for non-code files?
            # Let's stick to the previous behavior's fallback logic: if ast-grep *fails to run*, we use grep.
            # If ast-grep runs and finds nothing, we return nothing (for code).
            # BUT, to be safe and "improve" without breaking, let's run text search 
            # if structural search is empty, but mark them as "text matches".
            
            # Actually, let's just use the text search if structural returned nothing.
            strategy = "text"
            references = self._text_search(symbol_name, context_lines)

        return {
            "references": references,
            "total_count": len(references),
            "strategy": strategy,
            "note": f"Found {len(references)} references using {strategy} search."
        }

    def _ast_grep_search(self, symbol_name: str, context_lines: int) -> List[Dict[str, Any]]:
        """Search for symbol usages using ast-grep."""
        references = []
        try:
            # Use simple pattern matching the identifier
            cmd = [
                "ast-grep",
                "run",
                "--pattern", symbol_name,
                "--json",
                "-C", str(context_lines),
                str(self.root_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                try:
                    matches = json.loads(result.stdout)
                    for match in matches:
                        # Extract lines with context
                        # ast-grep json with -C returns 'lines' containing the snippet
                        code_snippet = match.get("lines", "").strip()
                        
                        # Get line number (start)
                        line_num = self._normalize_ast_grep_line(
                            match.get("range", {}).get("start", {}).get("line")
                        )
                        
                        references.append({
                            "file": match.get("file", ""),
                            "line": line_num,
                            "text": code_snippet,
                            "type": "code"
                        })
                except json.JSONDecodeError:
                    pass
        except FileNotFoundError:
            pass
            
        return references

    def _text_search(self, symbol_name: str, context_lines: int) -> List[Dict[str, Any]]:
        """Unified text search (ripgrep -> python fallback)."""
        references = []
        
        # Try ripgrep
        try:
            cmd = [
                "rg",
                "-w", 
                "--json",
                "-C", str(context_lines),
                symbol_name,
                str(self.root_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            data = json.loads(line)
                            if data.get("type") == "match":
                                match_data = data.get("data", {})
                                references.append({
                                    "file": match_data.get("path", {}).get("text", ""),
                                    "line": match_data.get("line_number", 0),
                                    "text": match_data.get("lines", {}).get("text", "").strip(),
                                    "type": "text"
                                })
                        except json.JSONDecodeError:
                            continue
                return references
        except FileNotFoundError:
            pass

        # Python fallback (simplified, no context for now to save complexity)
        return self._python_text_search(symbol_name)

    
    def _python_text_search(self, symbol_name: str) -> List[Dict[str, Any]]:
        """Fallback text search using Python when ripgrep is not available."""
        references = []
        gitignore_patterns = self._parse_gitignore()
        
        # Create word boundary pattern
        pattern = re.compile(r'\b' + re.escape(symbol_name) + r'\b')
        
        for file_path in self.root_path.rglob('*'):
            if not file_path.is_file():
                continue
            
            # Skip excluded files
            if self._should_exclude(file_path, gitignore_patterns):
                continue
            
            # Only search in source files
            if file_path.suffix.lower() not in LANGUAGE_MAP:
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if pattern.search(line):
                            references.append({
                                "file": str(file_path),
                                "line": line_num,
                                "text": line.strip()
                            })
            except Exception:
                continue
        
        return references
