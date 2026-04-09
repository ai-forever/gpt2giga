"""Runtime entrypoint for serving the FastAPI application."""

import sys

import uvicorn

from gpt2giga.app.cli import load_config
from gpt2giga.app.factory import create_app
from gpt2giga.common.app_meta import check_port_available, get_app_version
from gpt2giga.constants import SECURITY_FIELDS
from gpt2giga.logger import setup_logger


def run(
    *,
    config_loader=load_config,
    app_factory=create_app,
    logger_factory=setup_logger,
    port_checker=check_port_available,
    uvicorn_runner=uvicorn.run,
    exit_func=sys.exit,
    app_version_getter=get_app_version,
) -> None:
    """Load configuration, assemble the app, and start Uvicorn."""
    config = config_loader()
    proxy_settings = config.proxy_settings

    logger = logger_factory(
        log_level=proxy_settings.log_level,
        log_file=proxy_settings.log_filename,
        max_bytes=proxy_settings.log_max_size,
        enable_redaction=proxy_settings.log_redact_sensitive,
    )

    app = app_factory(config=config)
    app.state.logger = logger

    if proxy_settings.mode == "PROD" and proxy_settings.log_level == "DEBUG":
        logger.warning(
            "DEBUG log level in PROD mode may expose sensitive data. "
            "Consider using INFO or higher."
        )

    logger.info(f"Starting Gpt2Giga proxy server, version: {app_version_getter()}")
    logger.info(f"Proxy settings: {proxy_settings.model_dump(exclude=SECURITY_FIELDS)}")
    logger.info(f"Security posture: {proxy_settings.security.summary()}")
    logger.info(
        "GigaChat settings: "
        f"{config.gigachat_settings.model_dump(exclude={'password', 'credentials', 'access_token', 'key_file_password'})}"
    )

    if not port_checker(proxy_settings.host, proxy_settings.port):
        logger.error(
            f"Port {proxy_settings.port} is already in use on {proxy_settings.host}. "
            f"Possible zombie process — try: fuser -k {proxy_settings.port}/tcp"
        )
        exit_func(1)
        return

    uvicorn_runner(
        app,
        host=proxy_settings.host,
        port=proxy_settings.port,
        log_level=proxy_settings.log_level.lower(),
        ssl_keyfile=proxy_settings.https_key_file if proxy_settings.use_https else None,
        ssl_certfile=(
            proxy_settings.https_cert_file if proxy_settings.use_https else None
        ),
    )
