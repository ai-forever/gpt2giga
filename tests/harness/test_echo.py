from gpt2giga.harness.harnesses.echo import EchoHarness
from gpt2giga.harness.types import HarnessContext, HarnessRequest


def test_echo_harness_returns_prompt():
    result = EchoHarness().run(
        HarnessRequest(prompt="hello"),
        HarnessContext(proxy_url="http://127.0.0.1:8090"),
    )

    assert result.ok is True
    assert result.text == "hello"
    assert result.raw["api_mode"] == "v2"
