from integrations import get_integration_adapters


def test_all_integrations_disabled_by_default():
    adapters = get_integration_adapters()
    assert set(adapters) == {
        "cinema_engine", "repository_intelligence", "executive_bootstrap", "knowledge_graph",
    }
    for adapter in adapters.values():
        assert adapter.is_enabled() is False
        status = adapter.describe()
        assert status["enabled"] is False


def test_integrations_module_stays_import_light():
    # Regression guard: this module must stay import-light, matching
    # embeddings.py's semantic-search boundary. A future change adding a
    # real network client/SDK import here should be an explicit decision,
    # not something that slips in silently.
    with open("integrations.py") as fh:
        source = fh.read()
    for marker in ("torch", "tensorflow", "grpc", "httpx", "import requests"):
        assert marker not in source
