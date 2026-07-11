from gpt2giga_harness.harnesses.echo import EchoHarness
from gpt2giga_harness.registry import HarnessRegistry
from gpt2giga_harness.runtime import fingerprint


def test_worker_fingerprint_reports_both_distribution_versions(monkeypatch):
    versions = {
        "gpt2giga": "0.2.2a1",
        "gpt2giga-harness": "0.0.1",
    }
    monkeypatch.setattr(fingerprint.metadata, "version", versions.__getitem__)

    registry = HarnessRegistry()
    registry.register(EchoHarness())

    result = fingerprint.build_worker_fingerprint(registry)

    assert result["gpt2giga"] == "0.2.2a1"
    assert result["gpt2giga_harness"] == "0.0.1"
