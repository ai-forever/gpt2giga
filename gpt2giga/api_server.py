import sys

import uvicorn
from gigachat import GigaChat

from gpt2giga.app.factory import create_app as _create_app
from gpt2giga.app.run import run as _run
from gpt2giga.cli import load_config
from gpt2giga.common.app_meta import check_port_available, get_app_version
from gpt2giga.logger import setup_logger


def create_app(config=None):
    """Compatibility wrapper around the new application factory."""
    app = _create_app(
        config=config,
        config_loader=load_config,
        logger_factory=setup_logger,
        app_version_getter=get_app_version,
    )
    app.state.gigachat_factory_getter = lambda: GigaChat
    return app


def run():
    """Compatibility wrapper around the new runtime entrypoint."""
    _run(
        config_loader=load_config,
        app_factory=create_app,
        logger_factory=setup_logger,
        port_checker=check_port_available,
        uvicorn_runner=uvicorn.run,
        exit_func=sys.exit,
        app_version_getter=get_app_version,
    )


if __name__ == "__main__":
    run()
