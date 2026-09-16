import ast

from labassistant.context import LineRange
from labassistant.context.python_analysis import summarise_python_file
from labassistant.context.relevance import find_used_code, resolve_module_path
from tests.context_helpers import files


def used(project, path: str, start: int, end: int, exclude_enclosing: bool = True):
    summaries = {f.path: summarise_python_file(f) for f in project if f.is_python}
    selected = next(f for f in project if f.path == path)
    region = LineRange(start=start, end=end)
    enclosing = (
        next((s for s in summaries[path].symbols if s.lines.contains(region)), None)
        if exclude_enclosing
        else None
    )
    results = find_used_code(
        ast.parse(selected.content), summaries[path], region, summaries, enclosing
    )
    return [(u.path, u.symbol.qualname if u.symbol else None) for u in results]


PROJECT = files(
    {
        "main.py": """\
        import helpers
        import os
        from shapes import Square
        from maths.ops import double as twice
        from . import utils


        def local_helper():
            return 1


        def run(n):
            if n == 0:
                return local_helper()
            size = helpers.area(Square(n)) + twice(n)
            os.getcwd()
            utils.tidy()
            return run(n - 1)


        class Runner:
            def go(self):
                return self.prepare()

            def prepare(self):
                return 2
        """,
        "helpers.py": "def area(shape):\n    return shape.side ** 2\n",
        "shapes.py": "class Square:\n    def __init__(self, side):\n        self.side = side\n",
        "maths/ops.py": "def double(x):\n    return 2 * x\n",
        "maths/__init__.py": "",
        "utils.py": "def tidy():\n    pass\n",
    }
)


def test_resolves_calls_imports_classes_and_same_file_helpers() -> None:
    assert used(PROJECT, "main.py", 12, 18) == [
        ("main.py", "local_helper"),
        ("helpers.py", "area"),
        ("shapes.py", "Square"),
        ("maths/ops.py", "double"),
        ("utils.py", None),  # `from . import utils` is a module, included whole
    ]


def test_ignores_stdlib_and_the_enclosing_function_itself() -> None:
    result = used(PROJECT, "main.py", 12, 18)
    assert not any(path.startswith("os") for path, _ in result)
    assert ("main.py", "run") not in result


def test_module_attribute_does_not_also_include_whole_module() -> None:
    result = used(PROJECT, "main.py", 15, 15, exclude_enclosing=False)
    assert ("helpers.py", "area") in result
    assert ("helpers.py", None) not in result


def test_self_method_calls() -> None:
    assert used(PROJECT, "main.py", 23, 23, exclude_enclosing=False) == [
        ("main.py", "Runner.prepare")
    ]


def test_resolve_module_path_variants() -> None:
    paths = {"lab/a.py", "lab/pkg/__init__.py", "lab/pkg/b.py", "top.py"}
    assert resolve_module_path("lab/main.py", "a", 0, paths) == "lab/a.py"  # importer's folder
    assert resolve_module_path("lab/main.py", "top", 0, paths) == "top.py"  # project root
    assert resolve_module_path("lab/main.py", "pkg", 0, paths) == "lab/pkg/__init__.py"
    assert resolve_module_path("lab/pkg/b.py", "a", 2, paths) == "lab/a.py"  # from ..a import
    assert resolve_module_path("lab/main.py", "json", 0, paths) is None
