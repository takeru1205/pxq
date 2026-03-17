# pxq - A pueue-like CLI for local and RunPod job management

`pxq` is a command-line tool for managing job queues with support for local execution and RunPod GPU instances. It provides a simple interface for submitting, monitoring, and managing jobs with automatic pod lifecycle management.

## Features

- **Job Queue Management**: Submit, list, and monitor jobs with a simple CLI
- **Local Execution**: Run jobs locally for development and testing
- **RunPod Integration**: Execute jobs on GPU instances with automatic provisioning
- **Managed Mode**: Automatic pod stopping after job completion for cost savings
- **Web Dashboard**: Real-time job monitoring with auto-refresh
- **SSH Access**: Connect to running pods for debugging

## Installation

### From PyPI (Recommended for Production)

```bash
# Install via uv
uv tool install pxq

# Or install via pip
pip install pxq

# Verify installation
pxq --help
```

### From GitHub without Cloning (Recommended for Latest Version)

```bash
# Install directly from GitHub (no clone required)
uv tool install git+https://github.com/takeru1205/pxq.git

# Install a specific version/tag
uv tool install git+https://github.com/takeru1205/pxq.git@v0.1.0

# Verify installation
pxq --help
```

### From Source (Development)

```bash
# Clone the repository
git clone https://github.com/takeru1205/pxq.git
cd pxq

# Install in editable mode
uv tool install -e .

# Verify installation
pxq --help
```

After installation, you can use `pxq` directly:

```bash
pxq server
pxq add "python hello.py"
pxq ls
pxq status
```

### Using uv run (Development Only)

```bash
# Clone the repository
git clone https://github.com/takeru1205/pxq.git
cd pxq

# Install dependencies
uv sync

# Run using uv run (no installation needed)
uv run pxq --help
```

## Quick Start

1. Start the server:
   ```bash
   pxq server
   ```

2. In another terminal, add a job:
   ```bash
   pxq add "echo hello"
   ```

3. Check job status:
   ```bash
   pxq status
   ```

## CLI Commands

### `pxq server`

Start the pxq server. Required before using other commands.

```bash
pxq server [--port PORT] [--host HOST]
```

### `pxq add`

Add a new job to the queue.

```bash
pxq add COMMAND [--provider local|runpod] [--gpu TYPE] [--managed]
```

**Examples:**
```bash
# Local job
pxq add "python script.py"

# RunPod GPU job
pxq add "python train.py" --provider runpod --gpu "RTX4090:1"

# Managed RunPod job (auto-stop after completion)
pxq add "python train.py" --provider runpod --gpu "RTX4090:1" --managed
```

> For complete reference, see [docs/cli-reference.md](docs/cli-reference.md).

### `pxq ls`

List jobs in the queue.

```bash
pxq ls [--all]
```

### `pxq status`

Check job status.

```bash
pxq status [JOB_ID] [--all]
```

### `pxq ssh`

SSH into a running job's pod.

```bash
pxq ssh JOB_ID
```

### `pxq cancel`

Cancel a queued, provisioning, or uploading job.

```bash
pxq cancel JOB_ID
```

**Examples:**
```bash
# Cancel a queued job
pxq cancel 5

# Cancel a provisioning job
pxq cancel 28
```

**Note:** Running jobs cannot be cancelled. Use `pxq stop` to stop a running job.

### `pxq stop [JOB_ID]`

Stop a running job. If JOB_ID is provided, stops that specific job. Otherwise, stops the single running job (exactly one must be RUNNING).

**Examples:**
```bash
# Stop the single running job
pxq stop

# Stop a specific job by ID
pxq stop 42
```

**Note:** If no jobs are running or multiple jobs are running, an error is returned.

## Configuration

### Environment Variables

All configuration uses the `PXQ_` prefix:

| Variable | Description | Default |
|----------|-------------|---------|
| `PXQ_RUNPOD_API_KEY` | RunPod API key | None |
| `PXQ_MAX_PARALLELISM` | Maximum parallel jobs | 4 |
| `PXQ_LOG_MAX_SIZE_MB` | Log rotation limit per job | 100 |
| `PXQ_PROVISIONING_TIMEOUT_MINUTES` | Pod provisioning timeout | 15 |
| `PXQ_SERVER_HOST` | Server host | 127.0.0.1 |
| `PXQ_SERVER_PORT` | Server port | 8765 |
| `PXQ_DB_PATH` | Database path | ~/.pxq/pxq.db |

### Config File

Use a YAML config file with `--config`:

```yaml
# config.yaml
provider: runpod
gpu_type: RTX4090:1
managed: true
volume: vol-abc123

env:
  API_KEY: "{{ RUNPOD_SECRET_API_KEY }}"
  DATABASE_URL: "{{ RUNPOD_SECRET_DATABASE_URL }}"
```

pxq passes env values with `{{ RUNPOD_SECRET_* }}` placeholders directly to RunPod. RunPod expands these server-side at pod startup. Templates are NOT required for secrets.

## Dashboard

Access the web dashboard at `http://127.0.0.1:8765/` for real-time job monitoring.

**Features:**
- Job list with status
- Job detail view with logs
- Auto-refresh every 10 seconds

## Job Lifecycle

### Managed RunPod Jobs (auto-cleanup)
```
QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED -> STOPPING -> SUCCEEDED  (success)
                                               \-> FAILED -> STOPPING -> FAILED        (failure)
```
Managed jobs automatically delete the pod after completion. Successful jobs end at `SUCCEEDED`, failed jobs at `FAILED`.

### Manual Stop (`pxq stop`)
```
RUNNING (any job) -> STOPPING -> STOPPED
```
Manual stop via `pxq stop` always results in `STOPPED` status with pod deletion.

### Non-Managed RunPod Jobs (awaiting stop)
```
QUEUED -> PROVISIONING -> UPLOADING -> RUNNING  (remains until pxq stop)
```
Non-managed jobs stay in `RUNNING` status after command completion, awaiting explicit `pxq stop`.

### Local Jobs
```
QUEUED -> PROVISIONING -> UPLOADING -> RUNNING -> SUCCEEDED/FAILED/STOPPED
                                    \-> CANCELLED (terminal)
```

## Development

```bash
# Run tests
uv run pytest

# Type check
uv run pyright src/pxq

# Format code
uv run ruff format .
```

## License

MIT

## Troubleshooting

### Dashboard returns 500 for specific job

**Symptom:** `GET /jobs/{id}` or `GET /api/jobs/{id}` returns 500 Internal Server Error.

**Root cause:** Fixed in recent update. The issue was in `src/pxq/storage.py` where `sqlite3.Row.get()` was used, but `sqlite3.Row` does not have a `.get()` method.

**Fix:** Changed to bracket notation with key check:
```python
# Before (broken):
content_value = row.get("content") if "content" in row.keys() else None

# After (fixed):
content_value = row["content"] if "content" in row.keys() else None
```

**Verification:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8765/api/jobs/{id}
# Expected: 200 (or 404 if job not found)
```

### Check server status

```bash
# Check if server is running
uv run python -m pxq server status

# Verify listener on port 8765
lsof -nP -iTCP:8765 -sTCP:LISTEN
```

### Dashboard flickers on `/?all=true`

**Symptom:** Job list shows/hides intermittently when polling.

**Diagnosis:**
1. Check server singleton: `uv run python -m pxq server status`
2. Verify only one listener on port 8765
3. Check server logs: `cat ~/.pxq/server.log | tail -50`

**Fixed:** Regression tests added in `tests/dashboard/test_polling_stability.py`.
