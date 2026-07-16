from __future__ import annotations

import gzip
import json
from urllib.parse import urlparse

from fastapi.testclient import TestClient
import pytest

from gpt2giga_harness.config import HarnessConfig
from gpt2giga_harness.registry import create_default_registry
from gpt2giga_harness.ui.app import create_app
from gpt2giga_harness.ui.cockpit_v2 import (
    CockpitV2AssetNotFoundError,
    load_cockpit_v2_asset,
    load_cockpit_v2_manifest,
    load_cockpit_v2_shell,
)


def _client() -> TestClient:
    return TestClient(
        create_app(
            HarnessConfig(),
            registry=create_default_registry(include_entry_points=False),
        )
    )


def test_cockpit_v2_manifest_binds_hashed_split_and_precompressed_assets():
    manifest = load_cockpit_v2_manifest()

    assert manifest.entry == "index.html"
    assert set(manifest.initial).issubset(manifest.assets)
    assert any(name.startswith("assets/workbench-") for name in manifest.assets)
    assert any(name.startswith("assets/runs-") for name in manifest.assets)
    assert any(name.startswith("assets/markdown-") for name in manifest.assets)
    assert any(name.startswith("assets/raw-evidence-") for name in manifest.assets)
    assert all(
        asset.gzip_name is not None and asset.brotli_name is not None
        for name, asset in manifest.assets.items()
        if not name.endswith(".woff2")
    )
    assert all(
        asset.media_type == "font/woff2"
        and asset.gzip_name is None
        and asset.brotli_name is None
        for name, asset in manifest.assets.items()
        if name.endswith(".woff2")
    )
    assert "/cockpit-v2/assets/" in load_cockpit_v2_shell()


def test_cockpit_v2_loader_rejects_unknown_and_direct_compressed_paths():
    manifest = load_cockpit_v2_manifest()
    javascript = next(name for name in manifest.assets if name.endswith(".js"))
    compressed, asset = load_cockpit_v2_asset(javascript, encoding="gzip")
    identity, _ = load_cockpit_v2_asset(javascript)

    assert gzip.decompress(compressed) == identity
    assert asset.name == javascript
    with pytest.raises(CockpitV2AssetNotFoundError):
        load_cockpit_v2_asset(f"{javascript}.gz")
    with pytest.raises(CockpitV2AssetNotFoundError):
        load_cockpit_v2_asset("../manifest.json")


def test_cockpit_v2_is_default_and_legacy_remains_explicit_fallback():
    client = _client()

    default_redirect = client.get("/", follow_redirects=False)
    cockpit_default = client.get("/")
    legacy_recovery = client.get("/legacy/runs/run_123")
    cockpit = client.get("/cockpit-v2/work/session_123")
    unknown = client.get("/cockpit-v2/unknown")

    assert default_redirect.status_code == 307
    assert default_redirect.headers["location"] == "/cockpit-v2/work"
    assert default_redirect.headers["cache-control"] == "no-cache"
    assert cockpit_default.status_code == 200
    assert "gpt2giga Harness — Cockpit V2" in cockpit_default.text
    assert legacy_recovery.status_code == 200
    assert "gpt2giga Harness — Cockpit V2" not in legacy_recovery.text
    assert cockpit.status_code == 200
    assert "gpt2giga Harness — Cockpit V2" in cockpit.text
    assert cockpit.headers["content-security-policy"].startswith(
        "default-src 'none'; script-src 'self'; style-src 'self'"
    )
    assert cockpit.headers["x-content-type-options"] == "nosniff"
    assert unknown.status_code == 404


@pytest.mark.parametrize(
    ("legacy_path", "cockpit_path"),
    (
        ("/work", "/cockpit-v2/work"),
        ("/work/session_123", "/cockpit-v2/work/session_123"),
        ("/runs/run_123", "/cockpit-v2/runs/run_123"),
        (
            "/workflows/workflow_123",
            "/cockpit-v2/automation/workflows?selected=workflow_123",
        ),
        (
            "/scheduled/schedule_123",
            "/cockpit-v2/automation/schedules?selected=schedule_123",
        ),
        ("/agents", "/cockpit-v2/automation/agents"),
        ("/arena", "/cockpit-v2/evaluation/arena"),
        ("/evaluate", "/cockpit-v2/evaluation/evals"),
        ("/tools", "/cockpit-v2/integrations/mcp"),
        ("/approvals", "/cockpit-v2/runs"),
    ),
)
def test_legacy_default_deep_links_redirect_locally(legacy_path, cockpit_path):
    response = _client().get(legacy_path, follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == cockpit_path
    assert response.headers["cache-control"] == "no-cache"


def test_legacy_selected_deep_link_cannot_set_redirect_authority():
    response = _client().get(
        "/workflows/%5C%5Cevil.example",
        follow_redirects=False,
    )

    location = response.headers["location"]
    parsed = urlparse(location)
    assert response.status_code == 307
    assert parsed.scheme == ""
    assert parsed.netloc == ""
    assert parsed.path == "/cockpit-v2/automation/workflows"
    assert parsed.query == "selected=%5C%5Cevil.example"


@pytest.mark.parametrize(
    "path",
    (
        "/cockpit-v2/automation/agents",
        "/cockpit-v2/automation/workflows",
        "/cockpit-v2/automation/schedules",
        "/cockpit-v2/evaluation/arena",
        "/cockpit-v2/evaluation/evals",
        "/cockpit-v2/evaluation/baselines",
        "/cockpit-v2/integrations/harnesses",
        "/cockpit-v2/integrations/models",
        "/cockpit-v2/integrations/mcp",
        "/cockpit-v2/integrations/doctor",
    ),
)
def test_cockpit_v2_remaining_surface_deep_links_are_preserved(path):
    response = _client().get(path)

    assert response.status_code == 200
    assert "gpt2giga Harness — Cockpit V2" in response.text


def test_cockpit_v2_serves_negotiated_immutable_assets():
    client = _client()
    manifest = load_cockpit_v2_manifest()
    javascript = next(name for name in manifest.initial if name.endswith(".js"))

    response = client.get(
        f"/cockpit-v2/assets/{javascript}",
        headers={"Accept-Encoding": "gzip, br"},
    )
    identity = client.get(
        f"/cockpit-v2/assets/{javascript}",
        headers={"Accept-Encoding": "identity"},
    )

    assert response.status_code == 200
    assert response.headers["content-encoding"] == "br"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["vary"] == "Accept-Encoding"
    assert identity.status_code == 200
    assert "content-encoding" not in identity.headers
    assert len(identity.content) == manifest.assets[javascript].byte_count
    assert client.get(f"/cockpit-v2/assets/{javascript}.br").status_code == 404
    assert client.get("/cockpit-v2/assets/../manifest.json").status_code == 404


def test_cockpit_v2_serves_uncompressed_fonts_when_browser_accepts_brotli():
    client = _client()
    manifest = load_cockpit_v2_manifest()
    font = next(name for name in manifest.assets if name.endswith(".woff2"))

    response = client.get(
        f"/cockpit-v2/assets/{font}",
        headers={"Accept-Encoding": "gzip, br"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "font/woff2"
    assert "content-encoding" not in response.headers
    assert len(response.content) == manifest.assets[font].byte_count


def test_cockpit_v2_manifest_failure_is_clear_and_keeps_legacy_available(monkeypatch):
    from gpt2giga_harness.ui import routers
    from gpt2giga_harness.ui.cockpit_v2 import CockpitV2UnavailableError

    def unavailable() -> str:
        raise CockpitV2UnavailableError("missing")

    monkeypatch.setattr(routers.shell, "load_cockpit_v2_shell", unavailable)
    client = _client()

    failed = client.get("/cockpit-v2/work")

    assert failed.status_code == 503
    assert failed.json() == {
        "detail": (
            "Cockpit V2 packaged assets are unavailable; use /legacy while the "
            "installation is repaired"
        )
    }
    assert client.get("/legacy").status_code == 200


def test_cockpit_v2_manifest_is_content_free():
    manifest = load_cockpit_v2_manifest()
    serialized = json.dumps(
        {
            "entry": manifest.entry,
            "initial": manifest.initial,
            "assets": sorted(manifest.assets),
        }
    )

    for forbidden in ("prompt", "message", "token", "/Users/", "credential"):
        assert forbidden not in serialized
