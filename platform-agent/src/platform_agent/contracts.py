from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unexpected fields."""

    model_config = ConfigDict(extra="forbid")


class Confidence(StrEnum):
    """Allowed confidence levels for an agent diagnosis."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Evidence(StrictModel):
    """One observation supporting the agent's diagnosis."""

    source: str = Field(min_length=1)
    observation: str = Field(min_length=1)


class ToolResult(StrictModel):
    """Standard response returned by every agent tool."""

    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def validate_error_state(self) -> "ToolResult":
        if self.success and self.error is not None:
            raise ValueError(
                "A successful tool result cannot contain an error."
            )

        if not self.success and not self.error:
            raise ValueError(
                "A failed tool result must include an error."
            )

        return self


class IncidentReport(StrictModel):
    """Final evidence-based report produced by the agent."""

    summary: str = Field(min_length=1)
    probable_cause: str = Field(min_length=1)
    evidence: list[Evidence]
    confidence: Confidence
    recommended_action: str = Field(min_length=1)
    approval_required: bool
    tool_trace: list[ToolResult]
    errors: list[str] = Field(default_factory=list)
