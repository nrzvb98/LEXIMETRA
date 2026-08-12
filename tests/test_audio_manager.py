import os
import sys

from hala_rt.audio.manager import (
    _bundled_binary_dirs,
    _find_executable,
    _prepend_existing_binary_dirs_to_path,
)


def _make_executable(directory, name):
    path = directory / name
    path.write_text("")
    path.chmod(0o755)
    return path


def test_find_executable_prefers_bundled_dir_over_path_and_fallback(tmp_path, monkeypatch):
    bundled_bin = tmp_path / "bundled"
    path_bin = tmp_path / "path"
    homebrew_bin = tmp_path / "homebrew"
    bundled_bin.mkdir()
    path_bin.mkdir()
    homebrew_bin.mkdir()
    bundled_ffmpeg = _make_executable(bundled_bin, "ffmpeg")
    _make_executable(path_bin, "ffmpeg")
    _make_executable(homebrew_bin, "ffmpeg")
    monkeypatch.setenv("PATH", str(path_bin))

    assert _find_executable("ffmpeg", (bundled_bin,), (homebrew_bin,)) == str(bundled_ffmpeg)


def test_find_executable_accepts_windows_exe_suffix(tmp_path, monkeypatch):
    bundled_bin = tmp_path / "bundled"
    bundled_bin.mkdir()
    bundled_ffmpeg = _make_executable(bundled_bin, "ffmpeg.exe")
    monkeypatch.setenv("PATH", "")

    assert _find_executable("ffmpeg", (bundled_bin,), ()) == str(bundled_ffmpeg)


def test_find_executable_checks_fallback_dirs_after_path(tmp_path, monkeypatch):
    homebrew_bin = tmp_path / "homebrew"
    homebrew_bin.mkdir()
    fake_ffmpeg = _make_executable(homebrew_bin, "ffmpeg")
    monkeypatch.setenv("PATH", "")

    assert _find_executable("ffmpeg", fallback_dirs=(homebrew_bin,)) == str(fake_ffmpeg)


def test_prepend_existing_binary_dirs_keeps_bundled_before_path_and_fallback_after(tmp_path, monkeypatch):
    current_bin = tmp_path / "current"
    bundled_bin = tmp_path / "bundled"
    homebrew_bin = tmp_path / "homebrew"
    current_bin.mkdir()
    bundled_bin.mkdir()
    homebrew_bin.mkdir()
    monkeypatch.setenv("PATH", str(current_bin))

    _prepend_existing_binary_dirs_to_path((bundled_bin,), (homebrew_bin,))

    assert os.environ["PATH"].split(os.pathsep) == [
        str(bundled_bin),
        str(current_bin),
        str(homebrew_bin),
    ]


def test_bundled_binary_dirs_includes_pyinstaller_internal_bin(tmp_path, monkeypatch):
    executable = tmp_path / "HALA RT" / "HALA RT.exe"
    internal_dir = executable.parent / "_internal"
    executable.parent.mkdir()
    internal_dir.mkdir()
    executable.write_text("")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal_dir), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert internal_dir / "bin" in _bundled_binary_dirs()
