from __future__ import annotations

import importlib.util
import json
import sys
import threading
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_examples_smoke.py"


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("run_examples_smoke", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_api_versions_deduplicates_and_normalizes():
    smoke = load_smoke_module()

    assert smoke.parse_api_versions("v1,/v2,v1") == ("v1", "v2")


def test_parser_accepts_concurrency_short_option():
    smoke = load_smoke_module()

    args = smoke.build_parser().parse_args(["-n", "3", "--dry-run"])

    assert args.concurrency == 3


def test_discover_examples_skips_known_unsupported_by_default():
    smoke = load_smoke_module()

    cases = smoke.discover_example_cases(
        [smoke.EXAMPLES_ROOT],
        include_known_unsupported=False,
        exclude_patterns=[],
    )
    by_path = {case.rel_path: case for case in cases}

    assert "examples/openai/chat_completions/basic/chat_completion.py" in by_path
    assert by_path["examples/openai/files/basic.py"].skip_reason is not None
    assert by_path["examples/openai/agents/weather_handoff.py"].skip_reason is not None
    assert "examples/__init__.py" not in by_path


def test_child_execution_injects_api_version_and_local_base_url(tmp_path, capsys):
    smoke = load_smoke_module()
    example = tmp_path / "example.py"
    example.write_text(
        "\n".join(
            [
                'api_version = "v2"',
                "print(api_version)",
                'print("http://localhost:8090/v2/")',
            ]
        ),
        encoding="utf-8",
    )

    smoke.execute_example_file(
        example,
        api_version="v1",
        base_url="http://localhost:9000",
    )

    assert capsys.readouterr().out.splitlines() == [
        "v1",
        "http://localhost:9000/v1/",
    ]


def test_run_matrix_collects_failures_and_report_json(tmp_path):
    smoke = load_smoke_module()
    ok = tmp_path / "ok.py"
    ok.write_text('api_version = "v2"\nprint(api_version)\n', encoding="utf-8")
    bad = tmp_path / "bad.py"
    bad.write_text(
        'api_version = "v2"\nraise RuntimeError(f"boom {api_version}")\n',
        encoding="utf-8",
    )
    cases = [
        smoke.ExampleCase(path=ok, rel_path="ok.py"),
        smoke.ExampleCase(path=bad, rel_path="bad.py"),
    ]

    results = smoke.run_matrix(
        cases,
        api_versions=("v1",),
        base_url="http://localhost:8090",
        python=sys.executable,
        timeout=10,
        concurrency=1,
        fail_fast=False,
        verbose=False,
    )

    assert [result.status for result in results] == [smoke.PASS, smoke.FAIL]
    failure = results[1]
    assert failure.path == "bad.py"
    assert "RuntimeError: boom v1" in failure.stderr

    report_path = tmp_path / "report.json"
    smoke.write_json_report(
        report_path,
        results=results,
        base_url="http://localhost:8090",
        api_versions=("v1",),
        failure_output_lines=20,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"] == {
        smoke.PASS: 1,
        smoke.FAIL: 1,
        smoke.SKIP: 0,
    }
    assert report["results"][1]["path"] == "bad.py"
    assert "RuntimeError: boom v1" in report["results"][1]["stderr_tail"]


def test_run_matrix_uses_requested_concurrency(monkeypatch, tmp_path):
    smoke = load_smoke_module()
    cases = [
        smoke.ExampleCase(path=tmp_path / "one.py", rel_path="one.py"),
        smoke.ExampleCase(path=tmp_path / "two.py", rel_path="two.py"),
    ]
    lock = threading.Lock()
    both_started = threading.Event()
    active = 0
    started = 0
    max_active = 0

    def fake_run_example_subprocess(
        case,
        *,
        api_version,
        base_url,
        python,
        timeout,
    ):
        nonlocal active, max_active, started
        with lock:
            active += 1
            started += 1
            max_active = max(max_active, active)
            if started == 2:
                both_started.set()

        assert both_started.wait(1)

        with lock:
            active -= 1

        return smoke.ExampleResult(
            path=case.rel_path,
            api_version=api_version,
            status=smoke.PASS,
            duration_seconds=0.1,
        )

    monkeypatch.setattr(smoke, "run_example_subprocess", fake_run_example_subprocess)

    results = smoke.run_matrix(
        cases,
        api_versions=("v1",),
        base_url="http://localhost:8090",
        python=sys.executable,
        timeout=10,
        concurrency=2,
        fail_fast=False,
        verbose=False,
    )

    assert [result.status for result in results] == [smoke.PASS, smoke.PASS]
    assert max_active == 2
