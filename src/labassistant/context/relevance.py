"""Find project code that the selected code directly uses.

"Directly" means one step: names referenced in the region that resolve to a
function, class or module in the project. We do not follow calls transitively;
the repo map covers the wider codebase more cheaply.
"""

import ast
from pathlib import PurePosixPath

from pydantic import BaseModel

from labassistant.context.models import LineRange
from labassistant.context.python_analysis import FileSummary, ImportedName, Symbol


class UsedCode(BaseModel):
    path: str
    symbol: Symbol | None  # None means the whole module
    via: str  # how it was referenced, e.g. "metrics.total_size"


def find_used_code(
    tree: ast.Module,
    selected: FileSummary,
    region: LineRange,
    summaries: dict[str, FileSummary],
    exclude: Symbol | None = None,
) -> list[UsedCode]:
    """Project code referenced inside `region` of the selected file.

    `exclude` is usually the enclosing function, which is already in the context
    (and whose recursive calls to itself should not count as "used code").
    """
    # key -> (position of first reference, result)
    found: dict[tuple[str, str | None], tuple[tuple[int, int], UsedCode]] = {}
    enclosing_class = _enclosing_class(selected, region)

    # For `metrics.total_size`, the Name `metrics` is resolved as part of the
    # attribute, so it must not also count as "uses the whole metrics module".
    # ast.walk visits a parent before its children, so the attribute comes first.
    names_handled_by_attribute: set[int] = set()

    for node in _nodes_in_region(tree, region):
        result: UsedCode | None = None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            result = _resolve_attribute(
                node.value.id, node.attr, selected, summaries, enclosing_class
            )
            if result is not None:
                names_handled_by_attribute.add(id(node.value))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if id(node) in names_handled_by_attribute:
                continue
            result = _resolve_name(node.id, selected, summaries)

        if result is None or (
            exclude and result.path == selected.path and result.symbol == exclude
        ):
            continue
        key = (result.path, result.symbol.qualname if result.symbol else None)
        position = (node.lineno, node.col_offset)
        if key not in found or position < found[key][0]:
            found[key] = (position, result)

    # ast.walk goes breadth-first, so sort to list code in the order it is referenced.
    return [result for _, result in sorted(found.values(), key=lambda pair: pair[0])]


def resolve_module_path(
    importer_path: str, module: str, level: int, project_paths: set[str]
) -> str | None:
    """Map an import to a project file, or None for the standard library and packages.

    Absolute imports are tried from the project root and from the importing file's
    folder, because lab code is often run from its own folder without packages.
    """
    module_parts = module.split(".") if module else []
    importer_dir = PurePosixPath(importer_path).parent

    if level > 0:
        base = importer_dir
        for _ in range(level - 1):
            base = base.parent
        bases = [base]
    else:
        bases = [PurePosixPath("."), importer_dir]

    for base in bases:
        stem = base.joinpath(*module_parts) if module_parts else base
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            normalised = str(PurePosixPath(candidate))
            if normalised in project_paths:
                return normalised
    return None


def _nodes_in_region(tree: ast.Module, region: LineRange):
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line is not None and region.start <= line <= region.end:
            yield node


def _enclosing_class(summary: FileSummary, region: LineRange) -> Symbol | None:
    classes = [s for s in summary.symbols if s.kind == "class" and s.lines.contains(region)]
    return min(classes, key=lambda s: s.lines.end - s.lines.start, default=None)


def _import_for(name: str, summary: FileSummary) -> ImportedName | None:
    return next((i for i in summary.imports if i.local_name == name), None)


def _resolve_name(
    name: str, selected: FileSummary, summaries: dict[str, FileSummary]
) -> UsedCode | None:
    imported = _import_for(name, selected)
    if imported is None:
        local = selected.top_level_symbol(name)
        return UsedCode(path=selected.path, symbol=local, via=name) if local else None

    target_path = resolve_module_path(
        selected.path, imported.module, imported.level, set(summaries)
    )
    if target_path is None and imported.symbol is not None:
        # `from package import module` imports a module, not a symbol.
        dotted = f"{imported.module}.{imported.symbol}" if imported.module else imported.symbol
        module_path = resolve_module_path(selected.path, dotted, imported.level, set(summaries))
        return UsedCode(path=module_path, symbol=None, via=name) if module_path else None
    if target_path is None:
        return None
    if imported.symbol is None:
        return UsedCode(path=target_path, symbol=None, via=name)

    symbol = summaries[target_path].top_level_symbol(imported.symbol)
    # If the module doesn't define it (e.g. a re-export), fall back to the whole module.
    return UsedCode(path=target_path, symbol=symbol, via=name)


def _resolve_attribute(
    base: str,
    attr: str,
    selected: FileSummary,
    summaries: dict[str, FileSummary],
    enclosing_class: Symbol | None,
) -> UsedCode | None:
    if base == "self" and enclosing_class is not None:
        method = selected.symbol_by_qualname(f"{enclosing_class.qualname}.{attr}")
        return UsedCode(path=selected.path, symbol=method, via=f"self.{attr}") if method else None

    imported = _import_for(base, selected)
    if imported is None or imported.symbol is not None:
        return None  # attributes of imported classes are handled by including the class
    target_path = resolve_module_path(
        selected.path, imported.module, imported.level, set(summaries)
    )
    if target_path is None:
        return None
    symbol = summaries[target_path].top_level_symbol(attr)
    return UsedCode(path=target_path, symbol=symbol, via=f"{base}.{attr}")
