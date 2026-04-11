"""Package entrypoints."""


def run(*args, **kwargs):
    """Lazy CLI entrypoint wrapper."""
    from gpt2giga.app.run import run as _run

    return _run(*args, **kwargs)


__all__ = ["run"]

if __name__ == "__main__":
    run()
