"""Build the STU MCP distributions and their matching Markdown Skill ZIP."""
from __future__ import annotations

import argparse
import hashlib
import io
import subprocess
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

from stu_mcp import __version__

ROOT = Path(__file__).resolve().parents[1]
SKILL = "stu-campus"
SKILL_PATH = f"stu_mcp/skills/{SKILL}"


def validate_version(root: Path, tag: str | None) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    locked = next(package["version"] for package in lock["package"] if package["name"] == "stu-mcp")
    version = project["version"]
    if version != __version__ or version != locked:
        raise ValueError(f"project ({version}), runtime ({__version__}) and lock ({locked}) versions differ")
    if tag is not None:
        if tag != f"v{version}":
            raise ValueError(f"release tag {tag} must match v{version}")

        def git(*args: str) -> str:
            return subprocess.check_output(["git", *args], cwd=root, encoding="utf-8").strip()

        if git("rev-parse", "HEAD") != git("rev-parse", f"refs/tags/{tag}^{{commit}}"):
            raise ValueError(f"checkout does not match release tag {tag}")
        if git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError(f"release tag {tag} requires a clean checkout")
    return version


def check_metadata(contents: bytes, version: str, artifact: Path) -> None:
    metadata = BytesParser().parsebytes(contents)
    if metadata["Name"] != "stu-mcp" or metadata["Version"] != version:
        raise ValueError(f"{artifact.name} does not contain metadata for stu-mcp {version}")


def build_skill_archive(dist: Path, source: Path, version: str) -> Path:
    wheel = dist / f"stu_mcp-{version}-py3-none-any.whl"
    sdist = dist / f"stu_mcp-{version}.tar.gz"
    prefix = SKILL_PATH + "/"
    if source.is_symlink() or not source.is_dir():
        raise ValueError("the portable Skill requires regular Markdown files")
    source_root = source.resolve()
    resources = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError("the portable Skill requires regular Markdown files")
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            if (path.suffix != ".md" or "\\" in relative or ":" in relative
                    or not path.resolve().is_relative_to(source_root)):
                raise ValueError("the portable Skill requires regular Markdown files")
            resources[relative] = path.read_bytes()
    if "SKILL.md" not in resources:
        raise ValueError("the portable Skill is missing SKILL.md")

    with zipfile.ZipFile(wheel) as package:
        check_metadata(package.read(f"stu_mcp-{version}.dist-info/METADATA"), version, wheel)
        members = [info for info in package.infolist() if info.filename.startswith(prefix) and not info.is_dir()]
        packed = {info.filename.removeprefix(prefix): package.read(info) for info in members}
        if len(members) != len(packed) or packed != resources:
            raise ValueError(f"{wheel.name} must contain the exact Skill sources from this checkout")
    with tarfile.open(sdist, "r:gz") as package:
        package_root = f"stu_mcp-{version}"
        sdist_prefix = f"{package_root}/src/{prefix}"
        metadata = package.extractfile(f"{package_root}/PKG-INFO")
        if metadata is None:
            raise ValueError(f"{sdist.name} is missing package metadata")
        check_metadata(metadata.read(), version, sdist)
        sdist_members = [
            member for member in package.getmembers()
            if member.name.startswith(sdist_prefix) and not member.isdir()
        ]
        sdist_packed = {}
        for member in sdist_members:
            if not member.isfile():
                raise ValueError(f"{sdist.name} must contain the exact Skill sources from this checkout")
            extracted = package.extractfile(member)
            if extracted is None:
                raise ValueError(f"{sdist.name} must contain the exact Skill sources from this checkout")
            sdist_packed[member.name.removeprefix(sdist_prefix)] = extracted.read()
        if len(sdist_members) != len(sdist_packed) or sdist_packed != resources:
            raise ValueError(f"{sdist.name} must contain the exact Skill sources from this checkout")

    output = dist / f"{SKILL}-v{version}.zip"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative, contents in sorted(packed.items()):
            info = zipfile.ZipInfo(f"{SKILL}/{relative}")
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
    output.write_bytes(stream.getvalue())
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (wheel, sdist, output)
    )
    (dist / "SHA256SUMS.txt").write_text(checksums, encoding="ascii", newline="\n")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="verify the checked-out Git tag before a release build")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    dist = args.out_dir.resolve()
    version = validate_version(ROOT, args.tag)
    subprocess.run(["uv", "build", "--out-dir", str(dist)], cwd=ROOT, check=True)
    output = build_skill_archive(dist, ROOT / "src" / SKILL_PATH, version)
    print(f"Built {output}")


if __name__ == "__main__":
    main()
