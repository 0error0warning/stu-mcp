import hashlib
import importlib.util
import io
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stu_build_release", ROOT / "scripts/build_release.py")
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def build_inputs(directory, *, sdist_version="0.7.8", stale_wheel=False, extra_sdist_entry=None):
    version = "0.7.8"
    source = directory / "source"
    source.mkdir()
    (source / "references").mkdir()
    guide = {"SKILL.md": b"[scope](references/scope.md)\n",
             "references/scope.md": b"# Scope\n"}
    for name, body in guide.items():
        (source / name).write_bytes(body)

    wheel = directory / f"stu_mcp-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as package:
        package.writestr(f"stu_mcp-{version}.dist-info/METADATA", f"Name: stu-mcp\nVersion: {version}\n")
        for name, body in guide.items():
            package.writestr(f"{release.SKILL_PATH}/{name}", b"old guide" if stale_wheel else body)
    sdist = directory / f"stu_mcp-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as package:
        entries = {f"src/{release.SKILL_PATH}/{name}": body for name, body in guide.items()}
        if extra_sdist_entry is not None:
            entries[extra_sdist_entry[0]] = extra_sdist_entry[1]
        entries["PKG-INFO"] = f"Name: stu-mcp\nVersion: {sdist_version}\n".encode()
        for name, body in entries.items():
            member = tarfile.TarInfo(f"stu_mcp-{version}/{name}")
            member.size = len(body)
            package.addfile(member, io.BytesIO(body))
    return version, source, guide, wheel, sdist


def test_builds_versioned_markdown_zip_with_checksums_for_all_distributions(tmp_path):
    version, source, guide, wheel, sdist = build_inputs(tmp_path)
    output = release.build_skill_archive(tmp_path, source, version)
    assert output.name == f"stu-campus-v{version}.zip"
    with zipfile.ZipFile(output) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == {
            f"stu-campus/{name}": body for name, body in guide.items()
        }
    sums = (tmp_path / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()
    assert sums == [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in (wheel, sdist, output)
    ]


def test_rejects_packages_with_stale_skills_or_mismatched_versions(tmp_path):
    stale = tmp_path / "stale"
    stale.mkdir()
    version, source, *_ = build_inputs(stale, stale_wheel=True)
    with pytest.raises(ValueError, match="exact Skill sources"):
        release.build_skill_archive(stale, source, version)

    mismatch = tmp_path / "mismatch"
    mismatch.mkdir()
    version, source, *_ = build_inputs(mismatch, sdist_version="0.7.7")
    with pytest.raises(ValueError, match="does not contain metadata"):
        release.build_skill_archive(mismatch, source, version)
    assert not list(tmp_path.rglob("stu-campus-*.zip"))


def test_current_source_versions_match_and_reject_other_release_tags():
    assert release.validate_version(ROOT, None) == release.__version__
    with pytest.raises(ValueError, match="must match"):
        release.validate_version(ROOT, "v9999.0.0")


def test_rejects_extra_sdist_entries_and_non_markdown_sources(tmp_path):
    extra = tmp_path / "extra"
    extra.mkdir()
    version, source, *_ = build_inputs(
        extra, extra_sdist_entry=(f"src/{release.SKILL_PATH}/references/leftover.md", b"stale\n")
    )
    with pytest.raises(ValueError, match="exact Skill sources"):
        release.build_skill_archive(extra, source, version)

    non_md = tmp_path / "non-md"
    non_md.mkdir()
    version, source, *_ = build_inputs(non_md)
    (source / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    with pytest.raises(ValueError, match="regular Markdown files"):
        release.build_skill_archive(non_md, source, version)


def test_validate_version_git_tag_and_clean_checkout(tmp_path):
    git = shutil.which("git")
    if not git:
        pytest.skip("git is required for release tag validation test")
    repo = tmp_path / "repo"
    repo.mkdir()
    version = release.__version__
    tag = f"v{version}"
    (repo / "pyproject.toml").write_text(f'[project]\nname = "stu-mcp"\nversion = "{version}"\n',
                                         encoding="utf-8")
    (repo / "uv.lock").write_text(f'version = 1\n\n[[package]]\nname = "stu-mcp"\nversion = "{version}"\n',
                                   encoding="utf-8")

    def run_git(*args: str) -> None:
        subprocess.run([git, "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
                       cwd=repo, check=True, capture_output=True, text=True)

    run_git("init")
    run_git("add", "pyproject.toml", "uv.lock")
    run_git("commit", "-m", "initial")
    run_git("tag", tag)
    assert release.validate_version(repo, tag) == version

    dirty = repo / "untracked.txt"
    dirty.write_text("dirty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="clean checkout"):
        release.validate_version(repo, tag)
    dirty.unlink()

    (repo / "README.md").write_text("next\n", encoding="utf-8")
    run_git("add", "README.md")
    run_git("commit", "-m", "advance")
    with pytest.raises(ValueError, match="does not match release tag"):
        release.validate_version(repo, tag)
