from gpt2giga.storage.opensearch import (
    build_traffic_log_index_template,
    install_traffic_log_index_template,
)


def test_opensearch_template_contains_required_mappings():
    template = build_traffic_log_index_template()
    properties = template["template"]["mappings"]["properties"]

    assert template["index_patterns"] == ["gpt2giga-traffic*"]
    assert template["data_stream"] == {}
    assert properties["@timestamp"]["type"] == "date"
    assert properties["created_at"]["type"] == "date"
    assert properties["request_id"]["type"] == "keyword"
    assert properties["trace_id"]["type"] == "keyword"
    assert properties["model"]["type"] == "keyword"
    assert properties["model_effective"]["type"] == "keyword"
    assert properties["status_code"]["type"] == "integer"
    assert properties["metadata"]["type"] == "object"


def test_opensearch_template_can_disable_data_stream():
    template = build_traffic_log_index_template(
        index_pattern="gpt2giga-traffic-index-*",
        data_stream=False,
    )

    assert template["index_patterns"] == ["gpt2giga-traffic-index-*"]
    assert "data_stream" not in template


async def test_install_opensearch_template_uses_indices_api():
    class FakeIndices:
        def __init__(self):
            self.calls = []

        async def put_index_template(self, *, name, body):
            self.calls.append((name, body))
            return {"acknowledged": True}

    class FakeClient:
        def __init__(self):
            self.indices = FakeIndices()

    client = FakeClient()

    response = await install_traffic_log_index_template(
        client,
        name="traffic-template",
        index_pattern="traffic-*",
        data_stream=False,
    )

    assert response == {"acknowledged": True}
    name, body = client.indices.calls[0]
    assert name == "traffic-template"
    assert body["index_patterns"] == ["traffic-*"]
    assert "data_stream" not in body
