"""Request and response contracts for the /ask endpoint.

These models are the boundary of the system. Two things are deliberately kept
separate here:

* **Schema validity** — enforced by Pydantic (shape, types, allowed values).
* **Answer correctness** — NOT enforced here. A response can satisfy this schema
  and still be wrong; that is what the evaluation harness (D2) measures.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Access role of the caller. Determines which rows and documents are visible."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    EXECUTIVE = "executive"


class Department(StrEnum):
    """Organisational unit of the caller."""

    SALES = "sales"
    HR = "hr"
    FINANCE = "finance"
    ENGINEERING = "engineering"


class ToolUsed(StrEnum):
    """Which tool produced the evidence for the answer."""

    SQL = "sql"
    DOCS = "docs"
    BOTH = "both"
    NONE = "none"


class AskRequest(BaseModel):
    """An incoming question together with the caller's identity.

    The caller's role and department are part of the request rather than inferred
    later, because every data access downstream is scoped by them.
    """

    user_id: str = Field(min_length=1, max_length=64, examples=["emp_042"])
    role: Role
    department: Department
    question: str = Field(min_length=3, max_length=2000)


class Citation(BaseModel):
    """One piece of evidence backing a claim in the answer.

    A citation points at something retrievable: either a document chunk or the
    SQL statement that produced a number. Without this, an answer cannot be
    verified, and an unverifiable answer is treated as a failure.
    """

    source_type: ToolUsed
    # Document citations fill doc_id/chunk_id/quote; SQL citations fill sql.
    doc_id: str | None = None
    chunk_id: int | None = None
    quote: str | None = None
    sql: str | None = None


class AskResponse(BaseModel):
    """The structured answer returned to the caller."""

    request_id: str
    answer: str
    citations: list[Citation]
    tool_used: ToolUsed
    # True when the system refused to answer because the evidence it is allowed
    # to see does not support one. Refusing is a correct outcome, not an error.
    abstained: bool
    latency_ms: int


class HealthResponse(BaseModel):
    """Liveness payload: the process is up. Says nothing about dependencies."""

    status: str
    app: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    """Readiness payload: the process can actually serve traffic."""

    ready: bool
    checks: dict[str, str]
