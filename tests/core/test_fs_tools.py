from aaosa.core.fs_tools import (
    DEFAULT_FETCH_MAX_CHARS,
    FETCH_FILE_TOOL_NAME,
    make_fetch_file_tool,
    make_write_file_tool,
)
from aaosa.core.sandbox import Sandbox


def _ro(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    return Sandbox.for_reading(tmp_path)


def test_fetch_file_returns_content(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    assert tool.name == FETCH_FILE_TOOL_NAME
    assert tool.fn(path="a.txt") == "hello world"


def test_fetch_file_missing(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    assert tool.fn(path="nope.txt") == "[file not found: nope.txt]"


def test_fetch_file_escape_refused(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    out = tool.fn(path="../outside.txt")
    assert out.startswith("[refused:")


def test_fetch_file_binary_clear_error(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path))
    out = tool.fn(path="bin.dat")
    assert out.startswith("[cannot read bin.dat:")


def test_fetch_file_too_large_hard_refusal(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path), max_chars=10)
    out = tool.fn(path="big.txt")
    assert out.startswith("[file too large:")
    assert "100" in out and "10" in out


def test_fetch_file_under_limit_returns_full(tmp_path):
    tool = make_fetch_file_tool(_ro(tmp_path), max_chars=100)
    assert tool.fn(path="big.txt") == "x" * 100


def test_default_max_is_50k():
    assert DEFAULT_FETCH_MAX_CHARS == 50_000


def test_write_file_refused_on_readonly_sandbox(tmp_path):
    tool = make_write_file_tool(Sandbox.for_reading(tmp_path))
    out = tool.fn(path="new.txt", content="data")
    assert out.startswith("[refused:")
    assert not (tmp_path / "new.txt").exists()


def test_write_file_succeeds_on_writable_sandbox(tmp_path):
    tool = make_write_file_tool(Sandbox(root=tmp_path.resolve(), writable=True))
    out = tool.fn(path="new.txt", content="data")
    assert "new.txt" in out
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "data"
