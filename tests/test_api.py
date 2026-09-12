"""Tests for the API surface that exists on D0.

These check the contract, not answer quality: answer quality is measured by the
evaluation harness (D2), not by unit tests.
"""

from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)


def test_health_is_liveness_only() -> None:
    """/health must answer without touching the database."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "enterprise-ai-decision-platform"


def test_ask_rejects_unknown_role() -> None:
    """An unknown role is a contract violation, not a question to answer.

    Access scope is derived from the role, so a role the system does not know must
    never reach the data layer.
    """
    response = client.post(
        "/ask",
        json={
            "user_id": "emp_042",
            "role": "ceo_of_everything",
            "department": "sales",
            "question": "What was Q3 revenue?",
        },
    )

    assert response.status_code == 422


def test_ask_rejects_empty_question() -> None:
    response = client.post(
        "/ask",
        json={
            "user_id": "emp_042",
            "role": "employee",
            "department": "sales",
            "question": "",
        },
    )

    assert response.status_code == 422


def test_ask_is_honestly_unimplemented() -> None:
    """A valid request returns 501 until retrieval lands.

    This test exists so the skeleton cannot quietly start returning a fabricated
    answer: when /ask is implemented on D2 this test must be rewritten to assert
    real behaviour, which forces the change to be deliberate.
    """
    response = client.post(
        "/ask",
        json={
            "user_id": "emp_042",
            "role": "employee",
            "department": "sales",
            "question": "What is the expense approval limit for my role?",
        },
    )

    assert response.status_code == 501
    assert "request_id" in response.json()
