# Lab: File tree explorer

A file system is a tree: a directory contains files and other directories.
In this lab you will build a small in-memory model of a directory tree and
write **recursive** functions that explore it.

## Files

| File | What it contains |
|---|---|
| `tree.py` | The `Node` class (provided). |
| `loader.py` | `build_tree(name, spec)`: build a tree of `Node`s from nested dicts. |
| `metrics.py` | `total_size`, `depth` and `count_files`. |
| `search.py` | `find_path` and `directories_larger_than`. |
| `report.py` | `render`: an indented text listing of the tree. |

## Tasks

1. **`build_tree(name, spec)`**: `spec` is a dict mapping names to either an
   `int` (a file with that size in bytes) or another dict (a subdirectory).
   Return the root directory `Node` named `name`. Children must keep the
   order they appear in `spec`.
2. **`total_size(node)`**: the size of a file, or the sum of all file sizes
   anywhere inside a directory. An empty directory has size 0.
3. **`depth(node)`**: a file or an empty directory has depth 0. Otherwise it is
   1 more than the deepest child.
4. **`count_files(node)`**: the number of files (not directories) in the tree.
5. **`find_path(node, target)`**: the list of names from `node` down to the
   first node named `target` (depth-first, in child order), or `None` if there
   is no such node.
6. **`directories_larger_than(node, limit)`**: the names of every directory
   (including `node` itself) whose `total_size` is greater than `limit`,
   in depth-first pre-order.
7. **`render(node)`**: one line per node, indented two spaces per level.
   Files show `name (size B)`, directories show `name/ (total B)`.

All functions must be recursive. Do not modify the tree, and do not use
global variables. Run the tests with `pytest` from this folder.
