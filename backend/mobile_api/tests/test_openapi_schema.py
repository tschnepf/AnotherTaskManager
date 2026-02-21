from mobile_api.schema import generate_mobile_openapi, render_mobile_openapi_json, snapshot_path


def test_openapi_schema_contains_core_mobile_paths():
    schema = generate_mobile_openapi()
    paths = schema["paths"]
    assert "/api/mobile/v1/meta" in paths
    assert "/api/mobile/v1/sync/delta" in paths
    assert "/api/mobile/v1/intents/create-task" in paths
    assert "MobileErrorEnvelope" in schema["components"]["schemas"]


def test_openapi_snapshot_is_current():
    expected = snapshot_path().read_text(encoding="utf-8")
    generated = render_mobile_openapi_json()
    assert generated == expected
