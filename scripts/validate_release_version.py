"""Reject a release tag whose normalized PEP 440 version differs from the application."""

from __future__ import annotations

import argparse

from packaging.version import Version

from nightreign_overlay import __version__


def validate_tag(tag: str, app_version: str = __version__) -> None:
    if Version(tag.removeprefix("v")) != Version(app_version):
        raise ValueError(f"Release tag {tag!r} does not match application version {app_version!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    args = parser.parse_args()
    validate_tag(args.tag)


if __name__ == "__main__":
    main()
