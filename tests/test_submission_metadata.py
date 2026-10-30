from fastapi.testclient import TestClient

from src.server import app


def test_privacy_policy_is_publicly_served():
    response = TestClient(app).get("/privacy")

    assert response.status_code == 200
    assert "Privacy Policy" in response.text
    assert "GITHUB_TOKEN" in response.text
    assert "automatic retention period" in response.text


def test_openai_challenge_requires_configured_exact_token(monkeypatch):
    monkeypatch.delenv("OPENAI_APPS_CHALLENGE", raising=False)
    missing = TestClient(app).get("/.well-known/openai-apps-challenge")
    assert missing.status_code == 404

    token = "test-exact-openai-challenge-token"
    monkeypatch.setenv("OPENAI_APPS_CHALLENGE", token)
    response = TestClient(app).get("/.well-known/openai-apps-challenge")

    assert response.status_code == 200
    assert response.text == token
    assert response.headers["content-type"].startswith("text/plain")
