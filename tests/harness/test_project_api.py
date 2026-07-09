from fastapi.testclient import TestClient

from gpt2giga.harness.config import HarnessConfig
from gpt2giga.harness.registry import create_default_registry
from gpt2giga.harness.sessions import InMemoryHarnessSessionStore
from gpt2giga.harness.ui.app import create_app


def test_project_api_returns_workspace_project_defaults(tmp_path):
    client = _client(tmp_path / "data")

    response = client.get("/api/project", params={"workspace": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["root"] == str(tmp_path)
    assert body["project"]["name"] == tmp_path.name
    assert body["project"]["config_path"] is None
    assert body["config"]["exists"] is False
    assert body["defaults"]["harness"] == "codex-cli"
    assert body["defaults"]["api_mode"] == "v2"


def test_project_api_init_creates_config_and_reports_project_name(tmp_path):
    client = _client(tmp_path / "data")

    response = client.post(
        "/api/project/init",
        json={"workspace": str(tmp_path), "name": "demo-project"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["name"] == "demo-project"
    assert body["project"]["config_path"] == str(tmp_path / ".giga" / "harness.toml")
    assert body["config"]["exists"] is True
    assert body["config"]["project_name"] == "demo-project"
    assert (tmp_path / ".giga" / "harness.toml").exists()


def test_project_config_api_returns_parsed_config(tmp_path):
    client = _client(tmp_path / "data")
    client.post(
        "/api/project/init",
        json={"workspace": str(tmp_path), "name": "demo-project"},
    )

    response = client.get("/api/project/config", params={"workspace": str(tmp_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["exists"] is True
    assert body["config"]["defaults"]["harness"] == "codex-cli"
    assert "plan" in body["config"]["presets"]


def test_project_presets_api_lists_and_renders_presets(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    prompt_path = tmp_path / ".giga" / "prompts" / "plan.md"
    prompt_path.parent.mkdir(parents=True)
    config_path.write_text(
        """
[project]
name = "api-demo"

[presets.plan]
title = "Plan"
harness = "codex-cli"
mode = "plan"
workspace_policy = "current"
prompt_file = ".giga/prompts/plan.md"
""",
        encoding="utf-8",
    )
    prompt_path.write_text(
        "Plan {{project_name}} for {{user_prompt}} with {{selected_files}}",
        encoding="utf-8",
    )
    client = _client(tmp_path / "data")

    list_response = client.get(
        "/api/project/presets",
        params={"workspace": str(tmp_path)},
    )

    assert list_response.status_code == 200
    listed = list_response.json()["presets"]
    assert listed[0]["name"] == "plan"
    assert listed[0]["workspace_policy"] == "current"

    render_response = client.post(
        "/api/project/presets/plan/render",
        json={
            "workspace": str(tmp_path),
            "user_prompt": "ship slice",
            "selected_files": ["gpt2giga/harness/project.py"],
        },
    )

    assert render_response.status_code == 200
    rendered = render_response.json()["preset"]
    assert rendered["prompt"] == (
        "Plan api-demo for ship slice with gpt2giga/harness/project.py"
    )
    assert rendered["run"]["harness_id"] == "codex-cli"


def test_project_state_api_persists_last_cockpit_selection(tmp_path):
    data_dir = tmp_path / "data"
    client = _client(data_dir)

    response = client.patch(
        "/api/project/state",
        json={
            "workspace": str(tmp_path),
            "last_harness": "claude-code",
            "last_model": "GigaChat-2-Max",
            "last_api_mode": "v1",
            "last_run_mode": "review",
            "last_invocation_mode": "native",
            "last_selected_session": "sess_demo",
            "trusted": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["root"] == str(tmp_path)
    assert body["state"] == {
        "last_harness": "claude-code",
        "last_model": "GigaChat-2-Max",
        "last_api_mode": "v1",
        "last_run_mode": "review",
        "last_invocation_mode": "native",
        "last_selected_session": "sess_demo",
        "trusted": True,
    }
    state_path = data_dir / "projects" / body["project"]["id"] / "state.json"
    assert state_path.exists()

    project_response = client.get("/api/project", params={"workspace": str(tmp_path)})
    assert project_response.status_code == 200
    assert project_response.json()["state"]["last_harness"] == "claude-code"


def test_project_api_rejects_secret_project_config(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text('[defaults]\napi_key = "secret"\n', encoding="utf-8")
    client = _client(tmp_path / "data")

    response = client.get("/api/project", params={"workspace": str(tmp_path)})

    assert response.status_code == 400
    assert "secret key" in response.json()["detail"]


def test_project_api_init_overwrite_replaces_secret_config(tmp_path):
    config_path = tmp_path / ".giga" / "harness.toml"
    config_path.parent.mkdir()
    config_path.write_text('[defaults]\napi_key = "secret"\n', encoding="utf-8")
    client = _client(tmp_path / "data")

    response = client.post(
        "/api/project/init",
        json={
            "workspace": str(tmp_path),
            "name": "clean",
            "overwrite": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["project"]["name"] == "clean"
    assert "api_key" not in config_path.read_text(encoding="utf-8")


def _client(data_dir) -> TestClient:
    app = create_app(
        HarnessConfig(data_dir=str(data_dir)),
        registry=create_default_registry(include_entry_points=False),
        store=InMemoryHarnessSessionStore(),
    )
    return TestClient(app)
