"""Request bodies - these also generate the Swagger docs at /docs."""
from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., examples=["inspector"])
    password: str = Field(..., examples=["demo123"])


class GenerateRequest(BaseModel):
    lot: str = Field(..., examples=["LOT-L1-261119-C"])


class ReportPatch(BaseModel):
    sections: dict[str, Any] | None = None
    dispositions: dict[str, str] | None = None  # index of out_of_spec item -> disposition
    verify: list[str] | None = None             # defect ids verified by a person
    note: str = ""


class WorkflowAction(BaseModel):
    comment: str = ""


class RewriteRequest(BaseModel):
    section: Literal["executive_summary", "measurement_analysis"]
    instruction: str = "Make it clearer and more concise for a quality manager."


class RuleUpdate(BaseModel):
    changes: dict[str, Any]
    note: str = ""


class RuleCreate(BaseModel):
    rule: dict[str, Any]
    note: str = ""


class RuleImport(BaseModel):
    rules: list[dict[str, Any]]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=4000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
