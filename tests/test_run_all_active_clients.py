import src.run as run_module


class _FakeClient:
    def __init__(self, client_id: str):
        self.id = client_id


def test_run_all_active_clients_isolates_failures(monkeypatch):
    clients = [_FakeClient("client-a"), _FakeClient("client-b")]
    monkeypatch.setattr(
        run_module._client_repository,
        "list_clients",
        lambda status: clients,
    )

    def fake_run_for_client(client_id: str) -> str:
        if client_id == "client-a":
            raise ValueError("boom")
        return f"ok:{client_id}"

    monkeypatch.setattr(run_module, "run_for_client", fake_run_for_client)

    results = run_module.run_all_active_clients()

    assert results == ["ok:client-b"]
