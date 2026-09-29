"""Structured signals the LLM must return for each announcement (PRD section 8.1)."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GuidanceDirection(StrEnum):
    raised = "raised"
    maintained = "maintained"
    lowered = "lowered"
    withdrawn = "withdrawn"
    not_mentioned = "not_mentioned"


Expectation = Literal["beat", "inline", "miss", "unknown"]


class AnnouncementSignals(BaseModel):
    """What the LLM reads out of one announcement. It labels text; it never computes returns."""

    model_config = ConfigDict(extra="forbid")

    guidance_direction: GuidanceDirection
    revenue_vs_expectation: Expectation
    eps_vs_expectation: Expectation
    management_tone: float = Field(ge=-1.0, le=1.0)  # -1 very negative, 1 very positive
    forward_looking_confidence: float = Field(ge=0.0, le=1.0)
    risk_flags: list[str]  # short snake_case labels, e.g. "supply_chain", "margin_pressure"
    key_quotes: list[str] = Field(max_length=3)  # short supporting quotes from the text
    summary: str = Field(max_length=400)
    extraction_confidence: float = Field(ge=0.0, le=1.0)


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for provider-side structured output.

    Providers' strict modes need every property required and no extra properties. Numeric and
    length bounds are kept; whatever a provider ignores is still enforced by Pydantic afterwards.
    """
    schema = model.model_json_schema()

    def tighten(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            node.pop("title", None)
            for value in node.values():
                tighten(value)
        elif isinstance(node, list):
            for item in node:
                tighten(item)

    tighten(schema)
    return schema
