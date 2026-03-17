"""Regression tests for RunPod SSH execution wrapper behavior.

These tests encode the shell/environment mode decisions made in Task 1-2
and ensure the wrapper behavior is preserved across future changes.

Key references:
- Task 1 evidence: .sisyphus/evidence/task-1-shell-mode-matrix.md
- Task 2 evidence: .sisyphus/evidence/task-2-wrapper-fix.txt
- Task 3 evidence: .sisyphus/evidence/task-3-secondary-ssh-audit.txt
"""

from __future__ import annotations


from pxq.providers.runpod_exec import (
    REMOTE_STDOUT_PATH,
    REMOTE_STDERR_PATH,
    REMOTE_EXIT_CODE_PATH,
    REMOTE_DONE_PATH,
    _build_remote_wrapped_command,
)
from pxq.providers.runpod_ssh import (
    build_interactive_ssh_args,
    build_non_interactive_ssh_args,
    SSHConnectionInfo,
)


class TestRemoteWrapperCommand:
    """Tests for _build_remote_wrapped_command shell mode behavior.

    The wrapper uses `bash -il -c` to invoke an interactive login shell.
    This mode was chosen based on Task 1 same-Pod shell-mode comparison evidence:

    | Mode | KAGGLE Visible? |
    |------|-----------------|
    | Plain remote command | NO |
    | bash -l -c (login non-interactive) | NO |
    | bash -il -c (interactive login) | Closest match |
    | Manual interactive SSH | YES (user baseline) |

    Reference: .sisyphus/evidence/task-1-shell-mode-matrix.md
    """

    def test_wrapper_uses_bash_il_c(self) -> None:
        """Verify wrapper uses bash -il -c for interactive login shell.

        The `-i` flag ensures ~/.bashrc is read, which is critical for RunPod
        because RunPod's ~/.bashrc sources /etc/rp_environment containing
        exported secrets.

        See: https://github.com/runpod/containers/blob/main/container-template/start.sh
        """
        command = "echo hello"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # The wrapper must use bash -il -c for interactive login shell
        assert (
            "bash -il -c" in result
        ), f"Expected 'bash -il -c' in wrapper command, got: {result}"

    def test_wrapper_wraps_user_command_in_subshell(self) -> None:
        """Verify user command is wrapped in a subshell for proper redirection."""
        command = "python train.py"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # User command should be in a subshell with append redirection
        assert (
            "'( python train.py )'" in result or "( python train.py )" in result
        ), f"Expected user command wrapped in subshell, got: {result}"

    def test_wrapper_removes_old_marker_files(self) -> None:
        """Verify wrapper removes old marker files before execution."""
        command = "echo test"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Must clean up old files first
        assert "rm -f" in result
        assert REMOTE_STDOUT_PATH in result
        assert REMOTE_STDERR_PATH in result
        assert REMOTE_EXIT_CODE_PATH in result
        assert REMOTE_DONE_PATH in result

    def test_wrapper_touches_log_files_for_early_discovery(self) -> None:
        """Verify wrapper touches log files so log collector can discover them early."""
        command = "echo test"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Must touch files for early discovery by log_collector
        assert "touch" in result
        assert REMOTE_STDOUT_PATH in result
        assert REMOTE_STDERR_PATH in result

    def test_wrapper_changes_to_remote_dir(self) -> None:
        """Verify wrapper changes to the specified remote directory."""
        command = "ls -la"
        remote_dir = "/data/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Must change to remote_dir with proper quoting
        assert "cd" in result
        assert "/data/workspace" in result

    def test_wrapper_captures_stdout_with_append_redirection(self) -> None:
        """Verify stdout is captured with append redirection."""
        command = "echo output"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Stdout should be appended to the log file
        assert f">> {REMOTE_STDOUT_PATH}" in result

    def test_wrapper_captures_stderr_with_append_redirection(self) -> None:
        """Verify stderr is captured with append redirection."""
        command = "echo error >&2"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Stderr should be appended to the log file
        assert f"2>> {REMOTE_STDERR_PATH}" in result

    def test_wrapper_writes_exit_code_to_marker(self) -> None:
        """Verify exit code is written to marker file for polling.

        This is critical for exit-code polling mechanism:
        - The wrapper always exits 0 so SSH success means "wrapper completed"
        - Real command exit code is written to REMOTE_EXIT_CODE_PATH
        - Caller polls for REMOTE_DONE_PATH and reads exit code
        """
        command = "exit 1"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Exit code must be captured after command
        assert "printf" in result or "echo" in result
        assert REMOTE_EXIT_CODE_PATH in result
        assert "$?" in result

    def test_wrapper_touches_done_marker(self) -> None:
        """Verify done marker is touched after command completion."""
        command = "echo done"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Done marker signals completion for polling
        assert "touch" in result
        assert REMOTE_DONE_PATH in result

    def test_wrapper_uses_semicolon_for_exit_code_capture(self) -> None:
        """Verify exit code capture happens even if command fails.

        Using semicolon (;) instead of && ensures exit code is captured
        regardless of command success/failure.
        """
        command = "false"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # The pattern should have ; after the redirection, not &&
        # This ensures exit code is captured even on failure
        assert ";" in result
        # The exit code capture should come after the semicolon
        parts = result.split(";")
        exit_code_part = [p for p in parts if REMOTE_EXIT_CODE_PATH in p]
        assert (
            len(exit_code_part) > 0
        ), f"Expected exit code capture after semicolon, got: {result}"


class TestSshArgs:
    """Tests for SSH command construction via shared helpers.

    Note: Most SSH argument tests have been moved to tests/providers/test_runpod_ssh.py
    which tests build_interactive_ssh_args() and build_non_interactive_ssh_args().
    """

    def test_ssh_args_no_tty_flag_in_base_args(self) -> None:
        """Document that non-interactive SSH args do not include TTY allocation.

        Note: The `-tt` flag is NOT included in build_non_interactive_ssh_args().
        This is intentional - non-interactive mode is used for file transfers and
        log collection. Interactive mode (with -tt) is used for command execution
        via build_interactive_ssh_args().

        Task 1 tested SSH with `-tt` flag and found it still didn't expose
        secrets in non-interactive command mode. The shell-mode gap is at
        the RunPod infrastructure level, not fixable by TTY alone.
        """
        conn = SSHConnectionInfo(method="direct_tcp", host="192.168.1.1", port=22)
        result = build_non_interactive_ssh_args(conn)

        # Document current behavior: no -tt flag in non-interactive args
        assert "-tt" not in result, "Non-interactive SSH args should not include -tt"

    def test_interactive_args_includes_tt(self) -> None:
        """Verify interactive SSH args include -tt for PTY allocation."""
        conn = SSHConnectionInfo(method="direct_tcp", host="192.168.1.1", port=22)
        result = build_interactive_ssh_args(conn)

        assert "-tt" in result


class TestRemotePathConstants:
    """Tests for remote path constants used by the wrapper.

    These paths must align with log_collector.py search paths.
    See Task 3 evidence: .sisyphus/evidence/task-3-secondary-ssh-audit.txt
    """

    def test_stdout_path_is_workspace_relative(self) -> None:
        """Verify stdout path is under /workspace for RunPod compatibility."""
        assert REMOTE_STDOUT_PATH == "/workspace/pxq_stdout.log"

    def test_stderr_path_is_workspace_relative(self) -> None:
        """Verify stderr path is under /workspace for RunPod compatibility."""
        assert REMOTE_STDERR_PATH == "/workspace/pxq_stderr.log"

    def test_exit_code_path_is_workspace_relative(self) -> None:
        """Verify exit code path is under /workspace for consistency."""
        assert REMOTE_EXIT_CODE_PATH == "/workspace/pxq_exit_code"

    def test_done_marker_path_is_workspace_relative(self) -> None:
        """Verify done marker path is under /workspace for consistency."""
        assert REMOTE_DONE_PATH == "/workspace/pxq_done"

    def test_paths_use_pxq_prefix_for_namespace_isolation(self) -> None:
        """Verify paths use pxq_ prefix to avoid collision with user files."""
        assert REMOTE_STDOUT_PATH.startswith("/workspace/pxq_")
        assert REMOTE_STDERR_PATH.startswith("/workspace/pxq_")
        assert REMOTE_EXIT_CODE_PATH.startswith("/workspace/pxq_")
        assert REMOTE_DONE_PATH.startswith("/workspace/pxq_")


class TestExitCodePollingFormat:
    """Tests for exit-code polling mechanism format.

    The polling mechanism relies on:
    1. REMOTE_DONE_PATH marker file
    2. REMOTE_EXIT_CODE_PATH containing the exit code
    3. Polling command: test -f {REMOTE_DONE_PATH} && cat {REMOTE_EXIT_CODE_PATH}
    """

    def test_exit_code_file_format_is_simple_text(self) -> None:
        """Verify exit code is written as simple text via printf.

        The wrapper uses: printf '%s' "$?" > {REMOTE_EXIT_CODE_PATH}
        This ensures the file contains just the exit code number without
        trailing newline, making it easy to parse.
        """
        command = "exit 42"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # printf is used for clean exit code capture
        assert "printf" in result
        assert "'%s'" in result or '"%s"' in result
        assert '"$?"' in result or "'$?'" in result or "$?" in result

    def test_done_marker_is_created_after_exit_code(self) -> None:
        """Verify done marker is created after exit code is written.

        Order matters for polling:
        1. Command runs with redirection
        2. Exit code written to file
        3. Done marker created

        Poller checks for done marker, then reads exit code.
        """
        command = "echo test"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Find positions of exit code write and done marker touch
        # Done marker should come last
        exit_code_pos = result.find(REMOTE_EXIT_CODE_PATH)
        done_pos = result.rfind(REMOTE_DONE_PATH)

        # The last occurrence of done marker should be after exit code
        # (there may be earlier occurrences in rm -f cleanup)
        assert (
            done_pos > exit_code_pos
        ), f"Done marker should be created after exit code write. Got: {result}"


class TestCommandParity:
    """Tests for command string parity - ensuring commands are not rewritten before submission.

    These tests verify that the exact command string submitted by the user is
    preserved through the execution pipeline without modification. This is
    critical for reproducibility and debugging.

    Reference: Task 1 evidence - canonical verification target is
    /kaggle/input/spaceship-titanic (not spacesip-titanic)
    """

    def test_user_command_preserved_in_wrapper(self) -> None:
        """Verify the exact user command string is preserved in the wrapper.

        The command should NOT be rewritten, modified, or escaped differently
        than how it was submitted. This ensures reproducibility.
        """
        command = "python train.py --data /kaggle/input/spaceship-titanic"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # The exact command string must appear unmodified in the wrapper
        assert (
            command in result
        ), f"Expected exact command '{command}' to be preserved in wrapper, got: {result}"

    def test_command_with_special_chars_preserved(self) -> None:
        """Verify commands with special characters are preserved exactly."""
        command = "echo 'hello world' && ls -la | grep test"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # Special characters in the command must be preserved
        assert (
            "echo 'hello world'" in result or "echo 'hello world'" in result
        ), f"Expected special characters to be preserved, got: {result}"
        assert "grep test" in result, f"Expected pipe command preserved, got: {result}"

    def test_command_with_kaggle_path_not_typoed(self) -> None:
        """Verify canonical Kaggle path spaceship-titanic is NOT corrupted to spacesip-titanic.

        This is a regression test against path corruption that could occur
        if command string processing accidentally modifies paths.

        Reference: Task 1 evidence - canonical target is spaceship-titanic, not spacesip-titanic.
        """
        command = "python train.py --data /kaggle/input/spaceship-titanic"
        remote_dir = "/workspace"
        result = _build_remote_wrapped_command(command, remote_dir)

        # The correct path must be preserved
        assert (
            "spaceship-titanic" in result
        ), f"Expected 'spaceship-titanic' in command, got: {result}"
        # The typo should NOT appear
        assert (
            "spacesip-titanic" not in result
        ), f"Command should NOT contain typo 'spacesip-titanic', got: {result}"
