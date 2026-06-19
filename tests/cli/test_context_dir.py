# tests/cli/test_context_dir.py
import pytest

from aaosa.cli.context_dir import build_context_tree


def _mk(tmp_path, rel, content="x"):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def test_flat_sorted_relative_posix_paths(tmp_path):
    _mk(tmp_path, "src/main.py")
    _mk(tmp_path, "notes/roadmap.md")
    _mk(tmp_path, "notes/decisions.md")
    tree = build_context_tree(tmp_path)
    assert tree == "notes/decisions.md\nnotes/roadmap.md\nsrc/main.py"


def test_dotfiles_and_dotdirs_excluded(tmp_path):
    _mk(tmp_path, "keep.md")
    _mk(tmp_path, ".env", "secret")
    _mk(tmp_path, ".git/config", "[core]")
    _mk(tmp_path, ".obsidian/app.json", "{}")
    tree = build_context_tree(tmp_path)
    assert tree == "keep.md"


def test_gitignore_root_honored(tmp_path):
    _mk(tmp_path, ".gitignore", "*.log\nbuild/\n!keep.log\n")
    _mk(tmp_path, "app.py")
    _mk(tmp_path, "debug.log", "noise")
    _mk(tmp_path, "keep.log", "kept")
    _mk(tmp_path, "build/artifact.bin", "blob")
    tree = build_context_tree(tmp_path)
    assert tree == "app.py\nkeep.log"


def test_paths_are_posix_even_in_subdirs(tmp_path):
    _mk(tmp_path, "a/b/c.md")
    tree = build_context_tree(tmp_path)
    assert tree == "a/b/c.md"
    assert "\\" not in tree


def test_not_a_directory_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ValueError, match="not found or not a directory"):
        build_context_tree(missing)


def test_empty_after_filtering_raises(tmp_path):
    _mk(tmp_path, ".env", "only dotfiles")
    with pytest.raises(ValueError, match="no files"):
        build_context_tree(tmp_path)
