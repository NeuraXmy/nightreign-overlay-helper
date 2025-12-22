from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


_SECTION_RE = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
_VERSION_LINE_RE = re.compile(r"^(?P<prefix>\s*version\s*=\s*)\"(?P<value>[^\"]*)\"(?P<suffix>\s*)$")


class VersionError(ValueError):
    pass


def tag_to_pep440(tag: str) -> tuple[str, bool]:
    tag = tag.strip()
    if tag.startswith("refs/tags/"):
        tag = tag.removeprefix("refs/tags/")

    if not tag.startswith("v") or len(tag) < 2:
        raise VersionError(f"Tag must start with 'v', got: {tag!r}")

    raw = tag[1:]
    is_prerelease = "-" in raw

    if not is_prerelease:
        # Accept already-valid-ish release versions like 1.2.3
        if not re.fullmatch(r"\d+(?:\.\d+)*", raw):
            raise VersionError(
                "Release tag must look like v<digits[.digits...]>, "
                f"got: {tag!r}"
            )
        return raw, False

    base, suffix = raw.split("-", 1)
    if not re.fullmatch(r"\d+(?:\.\d+)*", base):
        raise VersionError(
            "Pre-release base must look like <digits[.digits...]>, "
            f"got: {tag!r}"
        )

    # Supported: -alpha.1/-a1, -beta.2/-b2, -rc.3/-rc3
    # Also support: -dev.4, -post.5, -pre.6/-preview.6
    m = re.fullmatch(
        r"(?P<label>alpha|a|beta|b|rc|pre|preview|dev|post)\.?" r"(?P<num>\d+)",
        suffix,
        flags=re.IGNORECASE,
    )
    if not m:
        raise VersionError(
            "Unsupported pre-release tag suffix. Use one of: "
            "-alpha.N, -beta.N, -rc.N, -dev.N, -post.N (e.g. v1.2.3-rc.1). "
            f"Got: {tag!r}"
        )

    label = m.group("label").lower()
    num = m.group("num")

    if label in {"alpha", "a"}:
        return f"{base}a{num}", True
    if label in {"beta", "b"}:
        return f"{base}b{num}", True
    if label == "rc":
        return f"{base}rc{num}", True
    if label in {"pre", "preview"}:
        # Map generic "pre" to rc for PEP 440 compatibility.
        return f"{base}rc{num}", True
    if label == "dev":
        return f"{base}.dev{num}", True
    if label == "post":
        # Note: post releases are not pre-releases, but tag naming used '-' so treat as special.
        return f"{base}.post{num}", True

    raise VersionError(f"Unhandled label: {label!r}")


def update_pyproject_version(pyproject_path: Path, new_version: str) -> bool:
    text = pyproject_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    in_project = False
    for idx, line in enumerate(lines):
        section_match = _SECTION_RE.match(line)
        if section_match:
            in_project = section_match.group("name").strip() == "project"
            continue

        if not in_project:
            continue

        m = _VERSION_LINE_RE.match(line)
        if not m:
            continue

        current = m.group("value")
        if current == new_version:
            return False

        if line.endswith("\r\n"):
            line_ending = "\r\n"
        elif line.endswith("\n"):
            line_ending = "\n"
        else:
            line_ending = ""

        lines[idx] = f"{m.group('prefix')}\"{new_version}\"{m.group('suffix')}{line_ending}"
        pyproject_path.write_text("".join(lines), encoding="utf-8")
        return True

    raise VersionError(
        "Could not find [project].version in pyproject.toml. "
        "Expected a line like: version = \"1.2.3\" under [project]."
    )


def read_pyproject_version(pyproject_path: Path) -> str:
    text = pyproject_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    in_project = False
    for line in lines:
        section_match = _SECTION_RE.match(line)
        if section_match:
            in_project = section_match.group("name").strip() == "project"
            continue

        if not in_project:
            continue

        m = _VERSION_LINE_RE.match(line)
        if m:
            return m.group("value")

    raise VersionError(
        "Could not find [project].version in pyproject.toml. "
        "Expected a line like: version = \"1.2.3\" under [project]."
    )


def append_github_env(name: str, value: str) -> None:
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        return
    with open(env_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update pyproject.toml [project].version from a git tag, with PEP 440 mapping."
    )
    parser.add_argument("--tag", required=True, help="Tag name, e.g. v1.2.3 or v1.2.3-rc.1")
    parser.add_argument("--file", default="pyproject.toml", help="Path to pyproject.toml")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not modify files; fail if pyproject.toml version does not match the tag",
    )
    parser.add_argument(
        "--set-github-env",
        action="store_true",
        help="Append PROJECT_VERSION and IS_PRERELEASE to $GITHUB_ENV when available",
    )
    args = parser.parse_args()

    pep440_version, is_prerelease = tag_to_pep440(args.tag)
    pyproject_path = Path(args.file)

    if args.check:
        current = read_pyproject_version(pyproject_path)
        if args.set_github_env:
            append_github_env("PROJECT_VERSION", pep440_version)
            append_github_env("IS_PRERELEASE", "true" if is_prerelease else "false")
            append_github_env("CURRENT_PROJECT_VERSION", current)

        if current != pep440_version:
            print(
                f"pyproject.toml version mismatch: current={current!r}, expected={pep440_version!r}",
                file=os.sys.stderr,
            )
            return 2

        print(pep440_version)
        return 0

    changed = update_pyproject_version(pyproject_path, pep440_version)

    if args.set_github_env:
        append_github_env("PROJECT_VERSION", pep440_version)
        append_github_env("IS_PRERELEASE", "true" if is_prerelease else "false")
        append_github_env("PYPROJECT_VERSION_CHANGED", "true" if changed else "false")

    print(pep440_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
