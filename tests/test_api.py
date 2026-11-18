from fastapi.testclient import TestClient

from market_intel.api import create_app


def test_health_reports_yahoo_toggle(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    body = TestClient(create_app(mi)).get("/health").json()
    assert body["providers"]["yahoo_finance"]["enabled"] is False
    assert body["datasets"]["analysts"].startswith("unavailable")


def test_yahoo_dataset_returns_503_when_disabled(make_mi):
    mi, _ = make_mi(yahoo_enabled=False)
    r = TestClient(create_app(mi)).get("/v1/tickers/AAPL/analysts")
    assert r.status_code == 503 and r.json()["error"] == "dataset_unavailable"


def test_profile_and_404(make_mi):
    mi, _ = make_mi()
    client = TestClient(create_app(mi))
    assert client.get("/v1/tickers/AAPL/profile").json()["cik"] == 320193
    r = client.get("/v1/tickers/NOPE/profile")
    assert r.status_code == 404 and r.json()["error"] == "symbol_not_found"


def test_api_key_required_when_configured(make_mi):
    mi, _ = make_mi()
    mi.settings = mi.settings.model_copy(update={"api_keys": "secret1,secret2"})
    client = TestClient(create_app(mi))
    assert client.get("/v1/tickers/AAPL/profile").status_code == 401
    assert client.get("/v1/tickers/AAPL/profile", headers={"X-API-Key": "secret2"}).status_code == 200
    assert client.get("/health").status_code == 200  # health stays open
