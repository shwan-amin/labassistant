"""Solution-leak check: find code in text a student could see.

Academic integrity is a hard rule, so this errs on the side of flagging. It is a
heuristic, not a proof: the evaluation counts how often it fires, and markers can
review flagged items in the dashboard.

Allowed: names in backticks (`total_size`, `node.children`), file paths, line numbers.
Flagged: code blocks, lines that read as code statements, and inline code that
contains a statement or assignment (`return 0`, `count = 0`, `for c in children`).
"""

import re

from pydantic import BaseModel

_FENCED_BLOCK = re.compile(r"```")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")

# Whole lines that look like Python statements.
_CODE_LINE_PATTERNS = [
    re.compile(r"^\s*(async\s+)?def\s+\w+\s*\("),
    re.compile(r"^\s*class\s+\w+\s*[(:]"),
    re.compile(r"^\s*for\s+\w+(\s*,\s*\w+)*\s+in\s+.+:\s*$"),
    re.compile(r"^\s*(if|elif|while)\s+[^,]+:\s*$"),
    re.compile(r"^\s*(else|try|finally)\s*:\s*$"),
    re.compile(r"^\s*except\b[\w\s,()]*:\s*$"),
    re.compile(r"^\s*with\s+.+\s+as\s+\w+\s*:\s*$"),
    re.compile(r"^\s*(return|yield)(\s+[\w\[\(\-\"'][^\s]*)?\s*([-+*/%<>=]|\(|\[|$)"),
    re.compile(r"^\s*[A-Za-z_][\w.\[\]]*\s*(=|\+=|-=|\*=|/=)\s*\S"),
    re.compile(r"^\s*(import|from)\s+[\w.]+(\s+import\s+\w+)?\s*$"),
    re.compile(r"^\s*(lambda\b|print\()"),
]

# Inline code that is more than a name: contains a statement or an assignment.
_INLINE_STATEMENT = re.compile(
    r"\b(return|yield|def|class|lambda|import)\b"
    r"|\bfor\s+\w+\s+in\b"
    r"|\b(if|while)\b.+:"
    r"|(?<![=!<>])=(?!=)"
    r"|[+\-*/]="
)


class LeakFinding(BaseModel):
    reason: str
    snippet: str


def find_leaks(text: str) -> list[LeakFinding]:
    findings: list[LeakFinding] = []
    if _FENCED_BLOCK.search(text):
        findings.append(LeakFinding(reason="code block", snippet=_shorten(text)))

    for line in text.splitlines():
        if any(pattern.search(line) for pattern in _CODE_LINE_PATTERNS):
            findings.append(LeakFinding(reason="code-like line", snippet=_shorten(line)))

    for match in _INLINE_CODE.finditer(text):
        if _INLINE_STATEMENT.search(match.group(1)):
            findings.append(
                LeakFinding(reason="inline code statement", snippet=_shorten(match.group(0)))
            )

    return findings


def _shorten(text: str, limit: int = 120) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."
