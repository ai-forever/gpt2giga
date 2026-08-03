import json
import sys

import uvicorn

from gpt2giga.app.factory import create_app
from gpt2giga.app.lifecycle import lifespan
from gpt2giga.app.settings import (
    build_provider_registry,
    load_app_config,
    setup_app_logger,
)
from gpt2giga.common.app_meta import check_port_available, get_app_version
from gpt2giga.constants import SECURITY_FIELDS
from gpt2giga.providers.profiles import ProviderMachineContracts, ProviderProfileError


PREFLIGHT_ERROR_SCHEMA_VERSION = "gpt2giga.error.v1"


def run():
    try:
        config = load_app_config()
    except ProviderProfileError as exc:
        if "--inspect-config" not in sys.argv:
            raise
        _exit_inspect_error(exc.code, exc.message)

    if config.inspect_config:
        try:
            registry = build_provider_registry(config)
        except ProviderProfileError as exc:
            _exit_inspect_error(exc.code, exc.message)
        except RuntimeError:
            _exit_inspect_error(
                "invalid_profile_schema",
                "Provider configuration preflight failed.",
            )
        manifest = ProviderMachineContracts(registry).inspect_manifest()
        print(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
        return

    proxy_settings = config.proxy_settings
    logger = setup_app_logger(config)

    app = create_app(config)
    app.state.logger = logger

    if proxy_settings.mode == "PROD" and proxy_settings.log_level == "DEBUG":
        logger.warning(
            "DEBUG log level in PROD mode may expose sensitive data. "
            "Consider using INFO or higher."
        )

    logger.info(f"Starting Gpt2Giga proxy server, version: {get_app_version()}")
    logger.info(f"Proxy settings: {proxy_settings.model_dump(exclude=SECURITY_FIELDS)}")
    logger.info(f"Security posture: {proxy_settings.security.summary()}")
    safe_gigachat_settings = config.gigachat_settings.model_dump(
        exclude={"password", "credentials", "access_token", "key_file_password"}
    )
    logger.info(f"GigaChat settings: {safe_gigachat_settings}")

    if not check_port_available(proxy_settings.host, proxy_settings.port):
        logger.error(
            f"Port {proxy_settings.port} is already in use on {proxy_settings.host}. "
            f"Possible zombie process — try: fuser -k {proxy_settings.port}/tcp"
        )
        sys.exit(1)

    uvicorn.run(
        app,
        host=proxy_settings.host,
        port=proxy_settings.port,
        log_level=proxy_settings.log_level.lower(),
        ssl_keyfile=proxy_settings.https_key_file if proxy_settings.use_https else None,
        ssl_certfile=(
            proxy_settings.https_cert_file if proxy_settings.use_https else None
        ),
    )


def _exit_inspect_error(code: str, message: str) -> None:
    """Write one bounded machine error to stdout and terminate preflight."""
    payload = {
        "schema_version": PREFLIGHT_ERROR_SCHEMA_VERSION,
        "error": {
            "code": code,
            "message": message,
            "details": [],
        },
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(2)


if __name__ == "__main__":
    run()


__all__ = ["create_app", "lifespan", "run"]
