"""A marker's review of one concept gap or quality note."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Decision(StrEnum):
    ACCEPT = "accept"  # the AI got it right
    OVERRIDE = "override"  # right idea, wrong concept or misconception
    REJECT = "reject"  # not a real gap / not a useful note


class ItemReview(BaseModel):
    item_type: Literal["gap", "note"]
    item_index: int = Field(ge=0)
    decision: Decision
    # For overridden gaps only: what the marker thinks the gap really is.
    concept_id: str | None = None
    misconception_id: str | None = None
    comment: str = Field(default="", max_length=2_000)
    reviewer: str = Field(default="marker", max_length=64)

    @model_validator(mode="after")
    def check_override(self) -> "ItemReview":
        if self.decision == Decision.OVERRIDE:
            if self.item_type != "gap":
                raise ValueError("only concept gaps can be overridden; accept or reject notes")
            if not self.concept_id:
                raise ValueError("an override needs a concept_id")
        elif self.concept_id or self.misconception_id:
            raise ValueError("concept_id and misconception_id are only used with override")
        return self


class ReviewsRequest(BaseModel):
    reviews: list[ItemReview] = Field(min_length=1, max_length=200)
