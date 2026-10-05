import httpx

from app.core import auth, warmup
from app.core.warmup import warm_up as real_warm_up


class CountingJwksClient:
    calls = 0

    def get_signing_keys(self):
        CountingJwksClient.calls += 1
        return []


def test_the_warm_up_fetches_the_azure_keys_and_opens_the_database_connections(monkeypatch):
    CountingJwksClient.calls = 0
    monkeypatch.setattr(auth, "jwks_client", CountingJwksClient)
    warnings = []
    monkeypatch.setattr(warmup.logger, "warning", lambda *args, **kwargs: warnings.append(args))

    real_warm_up()

    assert CountingJwksClient.calls == 1
    assert warnings == []
    assert warmup.apisolscore_engine.pool.checkedin() >= 2


def test_an_unreachable_azure_does_not_prevent_startup(monkeypatch):
    def unreachable():
        raise httpx.ConnectError("Azure is unreachable")

    monkeypatch.setattr(auth, "jwks_client", unreachable)
    warnings = []
    monkeypatch.setattr(warmup.logger, "warning", lambda *args, **kwargs: warnings.append(args))

    real_warm_up()

    assert [args[1] for args in warnings] == ["azure signing keys"]
