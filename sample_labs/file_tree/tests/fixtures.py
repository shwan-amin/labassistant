"""A shared example tree used by several test files."""

PROJECT_SPEC = {
    "README.md": 120,
    "src": {
        "main.py": 300,
        "utils": {"strings.py": 80, "maths.py": 50},
    },
    "docs": {},
    "data": {"big.csv": 5000},
}
