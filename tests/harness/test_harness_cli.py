from gpt2giga.harness import cli
from gpt2giga.harness.harnesses.direct_chat import DirectChatHarness
from gpt2giga.harness.types import HarnessResult


def test_cli_harness_list_outputs_direct_chat(capsys):
    exit_code = cli.main(["harness", "list"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "direct-chat" in output


def test_cli_chat_passes_api_mode_and_model(monkeypatch, capsys):
    captured = {}

    def fake_run(self, request, context):
        captured["request"] = request
        captured["context"] = context
        return HarnessResult(ok=True, text="ok")

    monkeypatch.setattr(DirectChatHarness, "run", fake_run)

    exit_code = cli.main(
        [
            "chat",
            "--api-mode",
            "v1",
            "--model",
            "GigaChat-2-Max",
            "hello",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.strip() == "ok"
    assert captured["request"].api_mode.value == "v1"
    assert captured["request"].model == "GigaChat-2-Max"
    assert captured["request"].prompt == "hello"
