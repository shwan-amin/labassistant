"""Dashboard presentation helpers, kept out of the Streamlit script so they can be tested."""

from typing import Any

MASTERY_COLOURS = {"unknown": "#8a8a8a", "emerging": "#d9a000", "secure": "#2e9e4f"}


def context_rows(context_summary: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per context item: what the diagnosis saw, and what the budget dropped."""
    return [
        {
            "kind": item["kind"],
            "item": item["title"],
            "tokens": item["tokens"],
            "status": item["status"],
        }
        for item in context_summary.get("items", [])
    ]


def usage_rows(session: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for label, key in (
        ("diagnosis", None),
        ("questions", "question_usage"),
        ("answers", "answer_usage"),
    ):
        usage = session["diagnosis"]["usage"] if key is None else session.get(key, {})
        rows.append(
            {
                "step": label,
                "input": usage.get("input_tokens", 0),
                "cached input": usage.get("cache_read_input_tokens", 0),
                "output": usage.get("output_tokens", 0),
            }
        )
    rows.append(
        {
            "step": "total",
            **{k: sum(r[k] for r in rows) for k in ("input", "cached input", "output")},
        }
    )
    return rows


def concept_map_dot(concept_map: dict[str, Any]) -> str:
    """Graphviz DOT for the concept graph, prerequisites pointing to the concepts that need them."""
    lines = [
        "digraph concepts {",
        "  rankdir=TB;",
        '  node [shape=box, style="rounded,filled", fontcolor=white];',
    ]
    for node in concept_map["nodes"]:
        label = f"{node['name']}\\n({node['state']})".replace('"', "'")
        colour = MASTERY_COLOURS.get(node["state"], "#8a8a8a")
        lines.append(f'  "{node["id"]}" [label="{label}", fillcolor="{colour}"];')
    for edge in concept_map["edges"]:
        lines.append(f'  "{edge["source"]}" -> "{edge["target"]}";')
    lines.append("}")
    return "\n".join(lines)


def review_summary(session: dict[str, Any], reviews: list[dict[str, Any]]) -> dict[str, int]:
    """How many items a marker has reviewed, and how often they agreed with the AI."""
    total = len(session["gaps"]) + len(session["diagnosis"]["quality_notes"])
    decisions = [r["decision"] for r in reviews]
    return {
        "items": total,
        "reviewed": len(reviews),
        "accepted": decisions.count("accept"),
        "overridden": decisions.count("override"),
        "rejected": decisions.count("reject"),
    }
