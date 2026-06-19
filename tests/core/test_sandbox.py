import os

import pytest

from aaosa.core.sandbox import Sandbox, SandboxViolation


def _tree(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "sub" / "b.txt").write_text("world", encoding="utf-8")
    return tmp_path


def test_for_reading_is_readonly_and_resolved(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    assert sb.writable is False
    assert sb.root == tmp_path.resolve()


def test_read_text_under_root(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    assert sb.read_text("a.txt") == "hello"
    assert sb.read_text("sub/b.txt") == "world"


def test_resolve_rejects_parent_traversal(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.resolve("../outside.txt")


def test_resolve_rejects_absolute_path(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.resolve(str(tmp_path.parent / "x.txt"))


def test_resolve_rejects_symlink_escaping_root(tmp_path):
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("top secret", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    link = root / "leak.txt"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted in this environment")
    sb = Sandbox.for_reading(root)
    with pytest.raises(SandboxViolation):
        sb.read_text("leak.txt")


def test_write_text_refused_on_readonly(tmp_path):
    sb = Sandbox.for_reading(_tree(tmp_path))
    with pytest.raises(SandboxViolation):
        sb.write_text("new.txt", "data")
    assert not (tmp_path / "new.txt").exists()


def test_write_text_allowed_when_writable(tmp_path):
    sb = Sandbox(root=tmp_path.resolve(), writable=True)
    sb.write_text("nested/new.txt", "data")
    assert (tmp_path / "nested" / "new.txt").read_text(encoding="utf-8") == "data"


def test_write_text_still_jailed_when_writable(tmp_path):
    sb = Sandbox(root=tmp_path.resolve(), writable=True)
    with pytest.raises(SandboxViolation):
        sb.write_text("../escape.txt", "data")


def test_for_reading_missing_root_raises(tmp_path):
    with pytest.raises(SandboxViolation):
        Sandbox.for_reading(tmp_path / "does-not-exist")


def test_for_reading_file_not_dir_raises(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    with pytest.raises(SandboxViolation):
        Sandbox.for_reading(f)
