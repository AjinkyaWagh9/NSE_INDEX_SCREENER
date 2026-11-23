from fastapi.testclient import TestClient
from web.server import app


def test_web_status():
    client = TestClient(app)
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "state" in data
    assert data["has_api_key"] is True


def test_web_rows():
    client = TestClient(app)
    r = client.get("/api/rows")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 130
    assert any(row["id"] == "NIFTY 50" for row in rows)
    assert any(row["id"] == "NIFTY PHARMA" for row in rows)


def test_web_index_html():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "NSE Index Screener" in r.text
