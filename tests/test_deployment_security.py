from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_traefik_dashboard_is_loopback_only_and_host_restricted():
    deployment = (ROOT / "deploy" / "traefik.yaml").read_text(encoding="utf-8")
    routes = (ROOT / "traefik" / "rules.yml").read_text(encoding="utf-8")

    assert "- 127.0.0.1:8080:8080" in deployment
    assert "- 8080:8080" not in deployment
    assert "Host(`localhost`) &&" in routes
