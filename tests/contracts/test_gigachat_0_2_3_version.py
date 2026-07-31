"""Installed GigaChat SDK version contract."""

from importlib.metadata import version

from packaging.version import Version


def test_installed_gigachat_is_stable_and_within_supported_range() -> None:
    installed = Version(version("gigachat"))

    assert installed >= Version("0.2.3")
    assert installed < Version("0.3.0")
    assert not installed.is_prerelease
