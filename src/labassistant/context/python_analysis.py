"""Static analysis of Python files with the standard `ast` module.

Nothing here executes student code: `ast.parse` only builds a syntax tree.
"""

import ast
from typing import Literal

from pydantic import BaseModel, Field

from labassistant.context.models import LineRange, ProjectFile

SymbolKind = Literal["function", "class", "method"]


class Symbol(BaseModel):
    kind: SymbolKind
    name: str
    qualname: str  # e.g. "Node.file" for a method
    signature: str  # e.g. "def total_size(node: Node) -> int"
    docstring: str  # first line only, to keep the repo map compact
    lines: LineRange  # includes decorators
    parent: str | None = None  # qualname of the enclosing class or function

    @property
    def is_top_level(self) -> bool:
        return self.parent is None


class ImportedName(BaseModel):
    """One name bound by an import statement.

    `import a.b as c`       -> local_name="c", module="a.b", symbol=None
    `from .x import y as z` -> local_name="z", module="x",   symbol="y", level=1
    """

    local_name: str
    module: str
    symbol: str | None = None
    level: int = 0
    line: int


class FileSummary(BaseModel):
    path: str
    module_docstring: str = ""
    imports: list[ImportedName] = Field(default_factory=list)
    symbols: list[Symbol] = Field(default_factory=list)
    parse_error: str | None = None

    def top_level_symbol(self, name: str) -> Symbol | None:
        return next((s for s in self.symbols if s.is_top_level and s.name == name), None)

    def symbol_by_qualname(self, qualname: str) -> Symbol | None:
        return next((s for s in self.symbols if s.qualname == qualname), None)


def parse_python(file: ProjectFile) -> ast.Module | str:
    """Return the syntax tree, or an error message if the file does not parse."""
    try:
        return ast.parse(file.content, filename=file.path)
    except SyntaxError as exc:
        return f"SyntaxError on line {exc.lineno}: {exc.msg}"
    except (ValueError, RecursionError, MemoryError) as exc:
        return f"could not parse: {type(exc).__name__}"


def summarise_python_file(file: ProjectFile) -> FileSummary:
    tree = parse_python(file)
    if isinstance(tree, str):
        return FileSummary(path=file.path, parse_error=tree)
    return FileSummary(
        path=file.path,
        module_docstring=_first_line(ast.get_docstring(tree)),
        imports=_collect_imports(tree),
        symbols=_collect_symbols(tree.body, parent=None, parent_is_class=False),
    )


def find_enclosing_symbol(summary: FileSummary, selection: LineRange) -> Symbol | None:
    """The innermost function or class that fully contains the selection."""
    containing = [s for s in summary.symbols if s.lines.contains(selection)]
    # Nested symbols are shorter, so the smallest range is the innermost one.
    return min(containing, key=lambda s: s.lines.end - s.lines.start, default=None)


def _collect_imports(tree: ast.Module) -> list[ImportedName]:
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # `import a.b` binds the name "a"; `import a.b as c` binds "c" to a.b.
                local = alias.asname or alias.name.split(".")[0]
                module = alias.name if alias.asname else alias.name.split(".")[0]
                imports.append(ImportedName(local_name=local, module=module, line=node.lineno))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue  # can't know which names a star import binds without running it
                imports.append(
                    ImportedName(
                        local_name=alias.asname or alias.name,
                        module=node.module or "",
                        symbol=alias.name,
                        level=node.level,
                        line=node.lineno,
                    )
                )
    return imports


def _collect_symbols(
    body: list[ast.stmt], parent: str | None, parent_is_class: bool
) -> list[Symbol]:
    symbols: list[Symbol] = []
    for node in body:
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        qualname = f"{parent}.{node.name}" if parent else node.name
        if isinstance(node, ast.ClassDef):
            kind: SymbolKind = "class"
        else:
            kind = "method" if parent_is_class else "function"
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)])
        symbols.append(
            Symbol(
                kind=kind,
                name=node.name,
                qualname=qualname,
                signature=_signature(node),
                docstring=_first_line(ast.get_docstring(node)),
                lines=LineRange(start=start, end=node.end_lineno or node.lineno),
                parent=parent,
            )
        )
        symbols.extend(
            _collect_symbols(
                node.body, parent=qualname, parent_is_class=isinstance(node, ast.ClassDef)
            )
        )
    return symbols


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(base) for base in node.bases)
        return f"class {node.name}({bases})" if bases else f"class {node.name}"
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"


def _first_line(docstring: str | None) -> str:
    return docstring.strip().splitlines()[0] if docstring and docstring.strip() else ""
