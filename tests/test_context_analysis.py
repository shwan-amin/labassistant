from textwrap import dedent

from labassistant.context import LineRange, ProjectFile
from labassistant.context.python_analysis import find_enclosing_symbol, summarise_python_file

SOURCE = dedent(
    '''\
    """Module docstring."""
    import os
    import collections.abc as cabc
    from .helpers import tidy as clean


    def top(a: int, b=2) -> int:
        """Add things.

        More detail.
        """
        return a + b


    class Shape(Base):
        """A shape."""

        @property
        def area(self):
            def inner():
                return 1
            return inner()
    '''
)


def summary():
    return summarise_python_file(ProjectFile(path="pkg/shapes.py", content=SOURCE))


def test_symbols_signatures_and_docstrings() -> None:
    symbols = {s.qualname: s for s in summary().symbols}

    assert symbols["top"].signature == "def top(a: int, b=2) -> int"
    assert symbols["top"].docstring == "Add things."
    assert symbols["top"].lines == LineRange(start=7, end=12)
    assert symbols["Shape"].signature == "class Shape(Base)"
    assert symbols["Shape.area"].kind == "method"
    assert symbols["Shape.area"].lines.start == 18  # includes the @property line
    assert symbols["Shape.area.inner"].kind == "function"


def test_imports() -> None:
    imports = {i.local_name: i for i in summary().imports}

    assert imports["os"].module == "os" and imports["os"].symbol is None
    assert imports["cabc"].module == "collections.abc"
    assert imports["clean"].symbol == "tidy" and imports["clean"].level == 1


def test_enclosing_symbol_is_innermost() -> None:
    s = summary()
    assert find_enclosing_symbol(s, LineRange(start=12, end=12)).qualname == "top"
    assert find_enclosing_symbol(s, LineRange(start=21, end=21)).qualname == "Shape.area.inner"
    assert find_enclosing_symbol(s, LineRange(start=22, end=22)).qualname == "Shape.area"


def test_selection_spanning_two_functions_has_no_function_enclosing() -> None:
    assert find_enclosing_symbol(summary(), LineRange(start=10, end=16)) is None


def test_unparseable_file_reports_error() -> None:
    broken = summarise_python_file(ProjectFile(path="bad.py", content="def f(:\n    pass\n"))

    assert broken.parse_error is not None and "line 1" in broken.parse_error
    assert broken.symbols == []
