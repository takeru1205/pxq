# Server Identity and Stale PID Reconciliation Design

## Overview

This document defines the canonical server identity verification logic for pxq server. The goal is to reliably detect the actual pxq server process even when the PID file contains a stale PID, and to guard against accidentally touching non-pxq processes.

## Problem Statement

### Current Issues

1. **Stale PID File**: The PID file (`~/.pxq/server.pid`) may contain a PID that no longer exists or belongs to a different process.
2. **No Identity Verification**: Current implementation only checks if a process with the PID exists via `os.kill(pid, 0)`, but does not verify if it's actually the pxq server.
3. **False Positives**: If another process happens to get the same PID, the current code incorrectly assumes it's the pxq server.
4. **No Port Ownership Check**: The current code doesn't verify if the process is actually listening on the expected server port.

### Known Issues from Context

- Live server (PID 28692) and PID file (dead PID 35336) were mismatched
- Live server's openapi was missing `/api/jobs/stop` and `/api/jobs/{job_id}/cancel` endpoints
- `pxq cancel 28` (provisioning) returned 404 because the server wasn't properly detected

## Solution Design

### Core Principles

1. **Port-based Detection**: The true pxq server is identified by the process listening on `server_host:server_port` (default 127.0.0.1:8765).
2. **Identity Verification**: Verify the process is actually pxq server by checking its command line contains `uvicorn pxq.server:app`.
3. **Stale PID Handling**: Automatically detect and clean up stale PID files.
4. **Safety Guard**: Never touch a process that doesn't match the pxq server identity.

### Function Definitions

#### `get_pxq_server_pid() -> Optional[int]`

Returns the PID of the actual pxq server process, ignoring stale PID files.

**Algorithm**:
1. Get the configured server port (default 8765)
2. Use `lsof -ti:{port}` to find the PID listening on that port
3. If no process is listening on the port, return None
4. Verify the process is pxq server by checking cmdline contains `uvicorn pxq.server:app` or `pxq.server:app`
5. If identity verified, return the PID
6. If identity not verified, return None (non-pxq process owns the port)

**Edge Cases**:
- No process listening on port → return None
- Multiple PIDs from lsof → use the first one (single instance design)
- Permission denied on lsof → fallback to reading PID file with identity check
- Non-pxq process owns the port → return None (safety guard)

#### `is_pxq_server_running() -> bool`

Returns True if the actual pxq server is running.

**Implementation**:
- Returns `get_pxq_server_pid() is not None`

#### `cleanup_stale_pid() -> bool`

Removes the stale PID file if it doesn't match the actual pxq server.

**Algorithm**:
1. Get the actual pxq server PID via `get_pxq_server_pid()`
2. Read the PID file via `read_pid()`
3. If PID file doesn't exist, return False (nothing to clean)
4. If actual server PID matches PID file, return False (not stale)
5. If actual server PID is None (no server) or different from PID file:
   - Delete the PID file
   - Return True (cleaned up stale file)

### Identity Verification Details

**Process Identity Check**:
- Read `/proc/{pid}/cmdline` (Linux) or use `ps` command (macOS)
- Check if cmdline contains any of:
  - `uvicorn pxq.server:app`
  - `pxq.server:app`
  - `pxq.server:create_app`

**Port Ownership Check**:
- Use `lsof -ti:{port}` to get PID listening on the port
- This is more reliable than trusting the PID file

### Platform Support

- **macOS**: Use `lsof -ti:{port}` and `ps -p {pid} -o command=`
- **Linux**: Use `lsof -ti:{port}` and read `/proc/{pid}/cmdline`

### Error Handling

1. **lsof not available**: Fallback to PID file check with identity verification
2. **Permission denied**: Handle gracefully, return None
3. **Process exits between checks**: Return None

## Testing Strategy

### Unit Tests

1. **Stale PID reconciliation happy path**:
   - PID file contains dead PID
   - Actual pxq server running on port
   - `get_pxq_server_pid()` returns actual server PID
   - `cleanup_stale_pid()` removes stale PID file

2. **Non-pxq listener failure guard**:
   - Non-pxq process listening on port 8765
   - `get_pxq_server_pid()` returns None
   - `is_pxq_server_running()` returns False

3. **Normal operation**:
   - pxq server running, PID file correct
   - All functions work correctly

4. **No server running**:
   - No process on port, no PID file
   - All functions return None/False

### Test Commands

```bash
# Scenario 1: stale PID reconciliation happy path
uv run pytest tests/unit -k "server_pid or stale pid or listener" -q | tee .sisyphus/evidence/task-1-server-identity.txt

# Scenario 2: non-pxq listener failure guard
uv run pytest tests/unit -k "non pxq listener or foreign process" -q | tee .sisyphus/evidence/task-1-server-identity-error.txt
```

## Dependencies

- This task is Wave 1 foundation task
- Task 2, 3, 4 depend on this task
- No external dependencies

## Files to Modify

- `src/pxq/server_pid.py` - Add new functions
- `tests/unit/test_server_pid.py` - Add new test cases
- `src/pxq/cli.py` - Update to use new functions (if needed)

## Backward Compatibility

- Existing functions (`get_server_pid()`, `is_server_running()`) remain unchanged
- New functions are additions, not replacements
- CLI commands continue to work with existing functions initially
