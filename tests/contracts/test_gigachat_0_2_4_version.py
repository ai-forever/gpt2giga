"""Installed GigaChat SDK native function schema contract."""

from importlib.metadata import version

from packaging.version import Version


def test_installed_gigachat_supports_native_function_schemas() -> None:
    installed = Version(version("gigachat"))

    assert installed >= Version("0.2.4a1")
    assert installed < Version("0.3.0")
