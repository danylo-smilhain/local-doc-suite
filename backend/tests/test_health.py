"""GET /api/health: liveness probe for the container healthcheck (task 11)."""


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
