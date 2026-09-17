"""LLM-assisted concept tagging for lecture chunks and slides.

Items are sent in batches so a whole lecture needs only a few requests (the
Gemini free tier allows about 5 per minute). Output is validated against the
concept graph; a human then reviews the saved tag file.
"""

import json

from pydantic import BaseModel, Field

from labassistant.knowledge.schema import ConceptGraph
from labassistant.llm.base import LLMClient, Usage
from labassistant.llm.structured import complete_json

BATCH_SIZE = 30
MAX_ITEM_CHARS = 1_500

TAGGING_SYSTEM = """\
You tag teaching material with the programming concepts it teaches.

For each item (a piece of a lecture transcript, or the text of a slide), list the ids \
of concepts from the concept list that the item actually explains or demonstrates. \
Merely mentioning a word is not enough. Many items teach none of these concepts \
(for example administration, or other topics); give those an empty list.

Reply with only a JSON object:
{"tags": [{"id": "<item id>", "concept_ids": ["<concept id>", ...]}]}
Include every item id exactly once.
"""


class ItemTags(BaseModel):
    id: str
    concept_ids: list[str] = Field(default_factory=list)


class TaggingOutput(BaseModel):
    tags: list[ItemTags]


class TaggingItem(BaseModel):
    id: str
    text: str


def tag_items(
    client: LLMClient, graph: ConceptGraph, items: list[TaggingItem], batch_size: int = BATCH_SIZE
) -> tuple[dict[str, list[str]], Usage, list[str]]:
    """Returns (concept ids per item id, usage, warnings). Unknown concept ids are dropped."""
    concept_list = "\n".join(f"- {c.id}: {c.name}. {c.description}" for c in graph.concepts)
    system = f"{TAGGING_SYSTEM}\nCONCEPTS:\n{concept_list}"

    tags: dict[str, list[str]] = {}
    usage = Usage()
    warnings: list[str] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        payload = [{"id": item.id, "text": item.text[:MAX_ITEM_CHARS]} for item in batch]
        output, batch_usage = complete_json(
            client,
            system=system,
            user="ITEMS:\n" + json.dumps(payload, indent=1),
            model=TaggingOutput,
        )
        usage = usage + batch_usage

        returned = {t.id: t.concept_ids for t in output.tags}
        for item in batch:
            concept_ids = returned.get(item.id)
            if concept_ids is None:
                warnings.append(f"no tags returned for {item.id}")
                concept_ids = []
            unknown = [c for c in concept_ids if graph.get_concept(c) is None]
            if unknown:
                warnings.append(f"dropped unknown concepts {unknown} for {item.id}")
            tags[item.id] = list(dict.fromkeys(c for c in concept_ids if graph.get_concept(c)))
    return tags, usage, warnings
