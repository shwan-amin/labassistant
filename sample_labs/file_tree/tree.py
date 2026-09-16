"""A node in an in-memory directory tree (provided, no changes needed)."""

from dataclasses import dataclass, field


@dataclass
class Node:
    """A file (with a size) or a directory (with children)."""

    name: str
    size: int = 0
    children: list["Node"] = field(default_factory=list)
    is_directory: bool = False

    @classmethod
    def file(cls, name: str, size: int) -> "Node":
        return cls(name=name, size=size)

    @classmethod
    def directory(cls, name: str, children: list["Node"] | None = None) -> "Node":
        return cls(name=name, children=list(children or []), is_directory=True)
