"""Tests for .pxqignore file support and optional workdir upload."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pxq.providers.runpod_exec import upload_directory, SSHError


class FakeProcess:
    """Fake subprocess for mocking asyncio.create_subprocess_exec."""

    def __init__(
        self,
        returncode: int,
        stdout: bytes = b"",
        stderr: bytes = b"",
    ) -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        pass

    async def wait(self) -> int:
        return self.returncode


@pytest.mark.asyncio
async def test_upload_directory_with_ignore_patterns(tmp_path: Path) -> None:
    """Test that upload_directory passes ignore patterns to tar command."""
    test_dir = tmp_path / "test_upload"
    test_dir.mkdir()
    (test_dir / "file1.txt").write_text("content1")

    mkdir_proc = FakeProcess(returncode=0)
    tar_proc = FakeProcess(returncode=0)
    ssh_proc = FakeProcess(returncode=0)

    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[mkdir_proc, tar_proc, ssh_proc]),
    ) as mock_exec:
        result = await upload_directory(
            local_dir=test_dir,
            host="test.example.com",
            port=2222,
            user="root",
            remote_dir="/workspace",
            timeout_seconds=60.0,
            ignore_patterns=["*.log", "__pycache__/"],
        )

    assert result is True
    assert mock_exec.call_count == 3

    # Second call should be local tar with --exclude options
    tar_call = mock_exec.call_args_list[1]
    tar_args = tar_call[0]  # All positional args
    assert "--exclude" in tar_args, f"Expected --exclude in {tar_args}"
    assert "*.log" in tar_args, f"Expected *.log in {tar_args}"
    assert "__pycache__/" in tar_args, f"Expected __pycache__/ in {tar_args}"


@pytest.mark.asyncio
async def test_upload_directory_without_ignore_patterns(tmp_path: Path) -> None:
    """Test that upload_directory works without ignore patterns."""
    test_dir = tmp_path / "test_upload"
    test_dir.mkdir()
    (test_dir / "file.txt").write_text("content")

    mkdir_proc = FakeProcess(returncode=0)
    tar_proc = FakeProcess(returncode=0)
    ssh_proc = FakeProcess(returncode=0)

    with patch(
        "pxq.providers.runpod_exec.asyncio.create_subprocess_exec",
        new=AsyncMock(side_effect=[mkdir_proc, tar_proc, ssh_proc]),
    ) as mock_exec:
        result = await upload_directory(
            local_dir=test_dir,
            host="test.example.com",
            port=2222,
            user="root",
            remote_dir="/workspace",
            timeout_seconds=60.0,
            ignore_patterns=None,
        )

    assert result is True
    tar_call = mock_exec.call_args_list[1]
    tar_args = tar_call[0]
    assert "--exclude" not in tar_args, f"Did not expect --exclude in {tar_args}"
