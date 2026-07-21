from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from gpt2giga_harness import entrypoint
from gpt2giga_harness.native_cli_contracts import NATIVE_NAMESPACE_SPECS
from gpt2giga_harness.native_cli_facade import (
    match_native_namespace,
    run_native_namespace,
)


@pytest.mark.parametrize("namespace", ("codex", "claude", "gemini"))
def test_facade_matches_only_reviewed_root_namespaces_with_opaque_suffix(namespace):
    suffix = ("", "duplicate", "duplicate", "Юникод", "line\nfeed", "--")

    invocation = match_native_namespace((namespace, *suffix))

    assert invocation == (NATIVE_NAMESPACE_SPECS[namespace], suffix)


@pytest.mark.parametrize(
    "argv",
    ((), ("doctor",), ("--help",), ("Codex",), ("openai", "--version")),
)
def test_facade_leaves_every_other_root_to_existing_harness_routing(argv):
    assert match_native_namespace(argv) is None


def test_facade_passes_provider_suffix_without_generic_option_parsing():
    calls = []

    def runner(spec, suffix, **kwargs):
        calls.append((spec, suffix, kwargs))
        return 23

    environment = {"PATH": "provider-path"}
    result = run_native_namespace(
        ("claude", "--help", "--json", "unknown", "--", "-prompt"),
        environment=environment,
        facade_executable="/installed/giga",
        runner=runner,
    )

    assert result == 23
    assert calls == [
        (
            NATIVE_NAMESPACE_SPECS["claude"],
            ("--help", "--json", "unknown", "--", "-prompt"),
            {
                "environment": environment,
                "facade_executable": "/installed/giga",
            },
        )
    ]


def test_console_entrypoint_routes_native_namespace_before_terminal_or_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(
        entrypoint,
        "run_native_namespace",
        lambda argv, **kwargs: calls.append((argv, kwargs)) or 37,
    )
    monkeypatch.setattr(
        entrypoint,
        "plan_terminal_dispatch",
        lambda *_args, **_kwargs: pytest.fail("terminal routing must not run"),
    )

    assert entrypoint.main(["gemini", "-p", "inspect", "--json"]) == 37
    assert calls == [
        (
            ["gemini", "-p", "inspect", "--json"],
            {"facade_executable": sys.argv[0]},
        )
    ]


def test_native_console_import_path_avoids_argparse_textual_and_full_cli():
    source = """
import sys
import gpt2giga_harness.entrypoint
blocked = {'argparse', 'textual', 'gpt2giga_harness.cli'}
print(','.join(sorted(name for name in sys.modules if name in blocked)))
"""

    completed = subprocess.run(
        (sys.executable, "-c", source),
        capture_output=True,
        text=True,
        check=True,
    )

    assert completed.stdout == "\n"


def _make_provider(path: Path) -> None:
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "os.write(1, json.dumps(sys.argv[1:], ensure_ascii=False).encode())\n"
        "os.write(2, b'provider-stderr')\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.mark.skipif(os.name == "nt", reason="POSIX console exec contract")
@pytest.mark.parametrize(
    ("namespace", "suffix"),
    (
        ("codex", ("exec", "--json", "inspect")),
        ("claude", ("-p", "inspect", "--output-format", "stream-json")),
        ("gemini", ("-p", "inspect", "--unknown-future-flag")),
        ("codex", ("--help",)),
        ("claude", ("--version",)),
        ("gemini", ("future-command", "--", "-prompt")),
    ),
)
def test_console_black_box_execs_exact_provider_with_untouched_suffix(
    tmp_path, namespace, suffix
):
    _make_provider(tmp_path / namespace)
    source = """
import sys
from gpt2giga_harness.entrypoint import main
raise SystemExit(main(sys.argv[1:]))
"""

    completed = subprocess.run(
        (sys.executable, "-c", source, namespace, *suffix),
        env={**os.environ, "PATH": os.fspath(tmp_path)},
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == list(suffix)
    assert completed.stderr == b"provider-stderr"


def test_missing_native_runtime_is_stderr_only_and_content_free(tmp_path, capfd):
    result = run_native_namespace(
        ("codex", "secret prompt", "--json"),
        environment={"PATH": os.fspath(tmp_path)},
    )

    assert result == 127
    captured = capfd.readouterr()
    assert captured.out == ""
    assert captured.err == "giga: native codex target unavailable\n"
    assert "secret" not in captured.err
