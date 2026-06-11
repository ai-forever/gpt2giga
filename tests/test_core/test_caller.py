from gpt2giga.core.caller import infer_request_caller


def test_infer_request_caller_detects_swagger_from_referer():
    caller = infer_request_caller(
        {
            "referer": "http://localhost:8090/docs",
            "user-agent": "Mozilla/5.0 Chrome/125.0",
        }
    )

    assert caller.name == "swagger-ui"
    assert caller.category == "ui"
    assert caller.ui == "swagger"
    assert caller.user_agent == "Mozilla/5.0 Chrome/125.0"
    assert caller.to_annotations()["caller"]["ui"] == "swagger"


def test_infer_request_caller_detects_code_agents():
    assert (
        infer_request_caller({"user-agent": "claude-code/1.0"}).agent == "claude-code"
    )
    assert infer_request_caller({"user-agent": "codex-cli/0.1"}).agent == "codex"
    assert infer_request_caller({"user-agent": "qwen-code/0.0.1"}).agent == "qwen-code"


def test_infer_request_caller_detects_openai_and_anthropic_sdks():
    openai = infer_request_caller({"user-agent": "OpenAI/Python 1.0.0"})
    anthropic = infer_request_caller(
        {
            "user-agent": "python-httpx/0.28",
            "anthropic-version": "2023-06-01",
        }
    )

    assert openai.category == "sdk"
    assert openai.sdk == "openai-python"
    assert openai.client_family == "openai"
    assert anthropic.category == "sdk"
    assert anthropic.sdk == "anthropic-compatible"
    assert anthropic.client_family == "anthropic"


def test_infer_request_caller_sanitizes_long_header_values():
    caller = infer_request_caller({"user-agent": "agent\n\t" + ("x" * 300)})

    assert "\n" not in caller.user_agent
    assert "\t" not in caller.user_agent
    assert len(caller.user_agent) == 256
