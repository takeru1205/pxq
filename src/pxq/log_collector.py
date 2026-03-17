"""Log collector for remote pod /var/log incremental collection.

This module provides periodic log collection from RunPod pods via SSH,
with incremental reading, rotation limits, and non-fatal warning recording.
"""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from pxq.config import Settings
from pxq.models import JobStatus
from pxq.providers.runpod_ssh import (
    SSHConnectionInfo,
    build_non_interactive_ssh_args,
)
from pxq.storage import create_artifact, get_artifacts
from pxq.models import JobStatus
from pxq.storage import create_artifact, get_artifacts


@dataclass
class LogFileState:
    """Tracks the collection state for a single log file.

    Attributes
    ----------
    path : str
        Full path to the log file on the remote pod.
    last_size : int
        Size of the file at last collection (bytes).
    last_position : int
        Byte position where next read should start.
    """

    path: str
    last_size: int = 0
    last_position: int = 0


@dataclass
class LogCollector:
    """Collects logs from /var/log on a remote pod via SSH.

    This collector performs incremental log collection at configurable
    intervals, stores logs as artifacts, and enforces rotation limits.
    Collection failures are recorded as warnings without failing the job.

    Attributes
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        Job ID to associate artifacts with.
    host : str
        Remote host address.
    port : int
        Remote SSH port.
    user : str
        SSH username.
    settings : Settings
        Application settings for rotation limits.
    collection_interval_seconds : float
        Interval between collection cycles.
    log_files : dict[str, LogFileState]
        State tracking for each discovered log file.
    total_bytes_collected : int
        Total bytes collected for this job.
    """

    db_path: Path | str
    job_id: int
    host: str
    port: int
    user: str = "root"
    settings: Settings = field(default_factory=Settings)
    collection_interval_seconds: float = 3.0
    log_files: dict[str, LogFileState] = field(default_factory=dict)
    total_bytes_collected: int = 0

    async def discover_log_files(self) -> list[str]:
        """Discover log files in /var/log on the remote pod.

        Returns
        -------
        list[str]
            List of discovered log file paths.

        Raises
        ------
        LogCollectionError
            If SSH command fails to execute.
        """
        # /var/log 内の .log ファイルと /workspace 内の *.log および pxq_*.log ファイルを検出
        command = (
            "find /var/log -maxdepth 1 -name '*.log' -type f 2>/dev/null; "
            "find /workspace -maxdepth 1 -name '*.log' -type f 2>/dev/null; "
            "find /workspace -maxdepth 1 -name 'pxq_*.log' -type f 2>/dev/null"
        )
        from typing import cast

        stdout = cast(str, await self._execute_ssh_command(command))

        files = []
        seen = set()
        for line in stdout.strip().split("\n"):
            line = line.strip()
            if line and line not in seen:
                files.append(line)
                seen.add(line)

        return files

    async def collect_logs(self) -> int:
        """Collect logs from /var/log on the remote pod.

        This method performs incremental collection by reading only new
        content since the last collection. Logs are stored as artifacts.

        Returns
        -------
        int
            Number of bytes collected in this cycle.

        Raises
        ------
        LogCollectionError
            If SSH command fails to execute.
        """
        # ログファイルを検出
        log_paths = await self.discover_log_files()

        total_collected = 0

        for log_path in log_paths:
            # 初回は状態を作成
            if log_path not in self.log_files:
                self.log_files[log_path] = LogFileState(path=log_path)

            state = self.log_files[log_path]

            # ファイルサイズを取得
            size_command = f"stat -c %s {shlex.quote(log_path)} 2>/dev/null || echo 0"
            size_output = await self._execute_ssh_command(size_command)
            try:
                current_size = int(size_output.strip())
            except ValueError:
                current_size = 0

            # 新しいコンテンツがあるか確認
            if current_size <= state.last_position:
                # ファイルが縮小した場合は最初から読み直す（ローテーション検出）
                if current_size < state.last_size:
                    state.last_position = 0
                continue

            # 増分読み取り
            read_command = f"tail -c +{state.last_position + 1} {shlex.quote(log_path)} 2>/dev/null"
            content = await self._execute_ssh_command(read_command, binary=True)

            if content:
                content_bytes = (
                    content if isinstance(content, bytes) else content.encode()
                )
                collected_size = len(content_bytes)

                # コンテンツをテキストにデコード
                content_text = content_bytes.decode("utf-8", errors="replace")

                # パスに基づいてartifact_typeを決定
                if "/workspace/pxq_stdout.log" in log_path:
                    artifact_type = "stdout"
                elif "/workspace/pxq_stderr.log" in log_path:
                    artifact_type = "stderr"
                else:
                    artifact_type = "log"

                # アーティファクトとして保存
                await create_artifact(
                    self.db_path,
                    self.job_id,
                    artifact_type=artifact_type,
                    path=log_path,
                    size_bytes=collected_size,
                    content=content_text,
                )

                # 状態を更新
                state.last_size = current_size
                state.last_position = current_size
                total_collected += collected_size
                self.total_bytes_collected += collected_size

        return total_collected

    async def check_rotation(self) -> bool:
        """Check if rotation is needed and perform it if necessary.

        Returns
        -------
        bool
            True if rotation was performed, False otherwise.
        """
        max_bytes = self.settings.log_max_size_mb * 1024 * 1024

        # 現在の総サイズを計算
        artifacts = await get_artifacts(self.db_path, self.job_id)
        log_artifacts = [a for a in artifacts if a.artifact_type == "log"]
        total_size = sum(a.size_bytes for a in log_artifacts)

        if total_size <= max_bytes:
            return False

        # ローテーション: 古いログから削除
        # アーティファクトは作成順でソートされているため、先頭から削除
        bytes_to_remove = total_size - max_bytes
        removed_bytes = 0

        async with aiosqlite.connect(self.db_path) as db:
            for artifact in log_artifacts:
                if removed_bytes >= bytes_to_remove:
                    break

                await db.execute(
                    "DELETE FROM artifacts WHERE id = ?",
                    (artifact.id,),
                )
                removed_bytes += artifact.size_bytes

            await db.commit()

        # ローテーションイベントを記録
        await record_collection_warning(
            self.db_path,
            self.job_id,
            f"Log rotation performed: removed {removed_bytes} bytes",
        )

        return True

    async def _execute_ssh_command(
        self,
        command: str,
        binary: bool = False,
    ) -> bytes | str:
        """Execute a command on the remote pod via SSH.

        Parameters
        ----------
        command : str
            Command to execute.
        binary : bool
            If True, return raw bytes; otherwise decode as UTF-8.

        Returns
        -------
        bytes | str
            Command output.

        Raises
        ------
        LogCollectionError
            If SSH command fails.
        """
        conn_info = SSHConnectionInfo(
            method="direct_tcp",
            host=self.host,
            port=self.port,
            username=self.user,
        )
        ssh_command = [
            *build_non_interactive_ssh_args(conn_info),
            command,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise LogCollectionError(f"Failed to start SSH process: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=30.0,
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise LogCollectionError("SSH command timed out") from exc

        if proc.returncode == 255:
            stderr_text = stderr.decode(errors="replace").strip()
            raise LogCollectionError(f"SSH connection failed: {stderr_text}")

        if binary:
            return stdout
        return stdout.decode(errors="replace")


class LogCollectionError(Exception):
    """Raised when log collection fails.

    This error indicates a transient collection failure that should be
    recorded as a warning, not as a job failure.
    """

    pass


async def record_collection_warning(
    db_path: Path | str,
    job_id: int,
    message: str,
) -> None:
    """Record a log collection warning event.

    This function records a warning in the job_events table without
    transitioning the job status. Collection failures should not cause
    job failures.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        Job ID to associate the warning with.
    message : str
        Warning message describing the issue.
    """
    now = datetime.now(UTC).isoformat()

    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO job_events (job_id, from_status, to_status, timestamp, message)
            VALUES (?, ?, ?, ?, ?)
            """,
            # to_status is required NOT NULL, use "warning" as placeholder for log collection warnings
            (
                job_id,
                None,
                JobStatus.RUNNING.value,
                now,
                f"[log_collection_warning] {message}",
            ),
        )
        await db.commit()


async def start_log_collection(
    db_path: Path | str,
    job_id: int,
    host: str,
    port: int,
    user: str = "root",
    settings: Optional[Settings] = None,
    collection_interval_seconds: float = 3.0,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Start periodic log collection for a job.

    This function runs a continuous log collection loop until the
    stop_event is set or an unrecoverable error occurs.

    Parameters
    ----------
    db_path : Path | str
        Path to the SQLite database.
    job_id : int
        Job ID to associate artifacts with.
    host : str
        Remote host address.
    port : int
        Remote SSH port.
    user : str
        SSH username.
    settings : Optional[Settings]
        Application settings. If None, defaults are used.
    collection_interval_seconds : float
        Interval between collection cycles.
    stop_event : Optional[asyncio.Event]
        Event to signal collection should stop.
    """
    if settings is None:
        settings = Settings()

    collector = LogCollector(
        db_path=db_path,
        job_id=job_id,
        host=host,
        port=port,
        user=user,
        settings=settings,
        collection_interval_seconds=collection_interval_seconds,
    )

    if stop_event is None:
        stop_event = asyncio.Event()

    while not stop_event.is_set():
        try:
            await collector.collect_logs()
            await collector.check_rotation()
        except LogCollectionError as exc:
            # 収集失敗は警告として記録し、ジョブは継続する
            await record_collection_warning(
                db_path,
                job_id,
                str(exc),
            )
        except Exception as exc:
            # 予期しないエラーも警告として記録
            await record_collection_warning(
                db_path,
                job_id,
                f"Unexpected error during log collection: {exc}",
            )

        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=collection_interval_seconds,
            )
            break
        except asyncio.TimeoutError:
            # タイムアウトは正常: 次の収集サイクルへ
            pass

    # Final collection to capture any remaining logs after stop event is set
    try:
        await collector.collect_logs()
        await collector.check_rotation()
    except LogCollectionError as exc:
        await record_collection_warning(
            db_path, job_id, f"Final collection failed: {exc}"
        )
    except Exception as exc:
        await record_collection_warning(
            db_path, job_id, f"Unexpected error in final collection: {exc}"
        )
