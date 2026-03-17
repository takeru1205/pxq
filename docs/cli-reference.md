# pxq CLI and Configuration Reference

## Overview

This page documents the currently implemented CLI and configuration surface for `pxq`. Adjacent examples are aligned to this reference where needed.

## Command Reference

### pxq add

Add a new job to the queue.

**Usage:**
```bash
pxq add [OPTIONS] COMMAND
```

**Arguments:**
- `COMMAND` (required): Command to execute

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--provider` | `-p` | Execution provider (`local`, `runpod`) |
| `--gpu` | | GPU type for RunPod (e.g., `RTX4090:1`) |
| `--region` | `-r` | RunPod data center (e.g., `EU-RO-1`) |
| `--cpu` | | Use CPU-only instance |
| `--volume` | `-v` | Network volume ID |
| `--volume-path` | | Mount path for network volume (default: `/volume`) |
| `--secure-cloud` | | Use Secure Cloud instead of Community Cloud |
| `--cpu-flavor` | | Comma-separated CPU flavors (e.g., `cpu3c,cpu3g`) |
|| `--template` | `-t` | RunPod Template ID |
|| `--image` | `-i` | RunPod container image (e.g., `ubuntu:22.04`) |
|| `--managed` | | Managed mode - auto-stop pod after completion |
| `--managed` | | Managed mode - auto-stop pod after completion |
| `--dir` | `-d` | Working directory |
| `--config` | `-c` | Config file path |

**Note:** `--gpu` and `--cpu` are mutually exclusive.

### pxq ls

List all jobs in the queue.

**Usage:**
```bash
pxq ls [OPTIONS]
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--all` | `-a` | Include terminal state jobs |

### pxq status

Check status of jobs.

**Usage:**
```bash
pxq status [OPTIONS] [JOB_ID]
```

**Arguments:**
- `JOB_ID` (optional): Job ID to check status. When omitted, shows all jobs.

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--all` | `-a` | Show all jobs including completed |

### pxq ssh

SSH into a running job's pod.

**Usage:**
```bash
pxq ssh [OPTIONS] JOB_ID
```

**Arguments:**
- `JOB_ID` (required): Job ID to connect to

**Preconditions:** Job must be in `RUNNING` state, have a `pod_id`, and expose SSH host.

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--help` | | Show this message and exit |

### pxq server

Start the pxq server.

**Usage:**
```bash
pxq server [OPTIONS]
```

**Options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--port` | `-p` | Port to run the server on |
| `--host` | `-h` | Host to bind the server to |

### pxq cancel

Cancel a queued job.

**Usage:**
```bash
pxq cancel JOB_ID
```

**Arguments:**
- `JOB_ID` (required): Job ID to cancel

**Note:** Only jobs in `QUEUED` status can be cancelled.

### pxq stop [JOB_ID]

Stop a running job. If JOB_ID is provided, stops that specific job. Otherwise, stops the single running job (exactly one must be RUNNING).

**Usage:**
```bash
pxq stop
```

**Arguments:**
- `JOB_ID` (optional): Job ID to stop. When omitted, stops the single running job.

**Preconditions:** Exactly one job must be in `RUNNING` status.

**Note:** If no jobs are running or multiple jobs are running, an error is returned. For RunPod jobs, the pod is deleted after stopping.

## Configuration Sources and Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **CLI flags** – Explicit command-line arguments (e.g., `--provider runpod`)
2. **YAML config file** – Values from the config file specified via `--config`
3. **Environment variables** – `PXQ_*` prefixed variables
4. **Built-in defaults** – Hardcoded defaults in the `Settings` class

When a value is not specified at a higher priority level, the next level is consulted. For example, if `--provider` is not given on the CLI, the value from the YAML config is used; if not in the config, environment variable `PXQ_PROVIDER` is checked; finally, the default value is used.

> **Note**: CLI flags take precedence even if the value is `False` or empty. The merge logic only falls back to config when the CLI value is `None` (i.e., the flag was not provided).

## Environment Variables

All environment variables use the `PXQ_` prefix. These are loaded via Pydantic Settings.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `PXQ_RUNPOD_API_KEY` | `str` | `None` | RunPod API key. Required when using `--provider runpod`. |
| `PXQ_MAX_PARALLELISM` | `int` | `4` | Maximum number of parallel jobs. |
| `PXQ_LOG_MAX_SIZE_MB` | `int` | `100` | Log rotation size limit per job (MB). |
| `PXQ_PROVISIONING_TIMEOUT_MINUTES` | `int` | `15` | Timeout for pod provisioning in minutes. |
| `PXQ_SERVER_HOST` | `str` | `"127.0.0.1"` | Server bind host. |
| `PXQ_SERVER_PORT` | `int` | `8765` | Server bind port. |
| `PXQ_CORS_ORIGINS` | `list[str]` | `["http://localhost", "http://localhost:3000", "http://localhost:5173", "http://127.0.0.1", "http://127.0.0.1:3000", "http://127.0.0.1:5173"]` | Comma-separated list of allowed CORS origins. |
| `PXQ_DB_PATH` | `Path` | `~/.pxq/pxq.db` | Path to the SQLite database file. |
| `PXQ_RUNPOD_SSH_KEY_PATH` | `Path` | `None` | Path to SSH private key for RunPod SSH connections. |

> **Note**: List values like `PXQ_CORS_ORIGINS` should be comma-separated when set via environment variable.

## YAML Config File Keys

The following keys are supported in YAML config files. These are merged with CLI arguments via `merge_config_with_cli()`.

| Key | Type | Description |
|-----|------|-------------|
| `provider` | `str` | Job provider: `local` or `runpod`. |
| `gpu_type` | `str` | GPU type for RunPod (e.g., `RTX4090:1`). **Note**: `gpu` is also accepted as a backward-compatible alias (e.g., `gpu: RTX4090:1`), but `gpu_type` is the canonical key. |
| `region` | `str` | RunPod region for pod deployment. |
| `cpu_count` | `int` | Number of CPU cores to allocate. |
| `volume` | `str` | Volume ID for persistent storage. |
| `volume_path` | `str` | Mount path for the volume (requires `volume` to be set). |
| `secure_cloud` | `bool` | Enable secure cloud mode for RunPod. |
|| `cpu_flavor_ids` | `list[str]` | List of CPU flavor IDs for instance selection. |
|| `template_id` | `str` | Template ID for RunPod pod configuration. |
|| `image_name` | `str` | Container image for RunPod pod (e.g., `ubuntu:22.04`). Mutually exclusive with `template_id`. |
|| `env` | `dict[str, str]` | Environment variables to pass to the job. Supports `{{ RUNPOD_SECRET_* }}` placeholders. |
|| `managed` | `bool` | Enable managed mode (auto-stop pod after job completion). |
|| `workdir` | `str` | Working directory for job execution. Relative paths are resolved to absolute. |

|| `managed` | `bool` | Enable managed mode (auto-stop pod after job completion). |
|| `workdir` | `str` | Working directory for job execution. Relative paths are resolved to absolute. |

> **Warning**: Older examples may show deprecated keys. These are **not** valid and should not be used.

## Examples

### Start the Server First

Before using any `pxq` commands, start the server:

```bash
pxq server [--port PORT] [--host HOST]
```

### Local Job Example

```bash
pxq add "python script.py"
```

### RunPod GPU Example

```bash
pxq add "python train.py" --provider runpod --gpu "RTX4090:1" --managed
```

### YAML Config Example

```yaml
# config.yaml
provider: runpod
gpu_type: RTX4090:1
managed: true
volume: vol-abc123
env:
  API_KEY: "{{ RUNPOD_SECRET_API_KEY }}"
```

```bash
pxq add "python train.py" --config config.yaml
```

## Known Constraints

- **`--gpu` and `--cpu` are mutually exclusive**: Cannot specify both flags.
- **`--image` and `--template` are mutually exclusive**: Cannot specify both flags. Choose either a custom image or a template.
- **`volume_path` requires `volume`**: Only effective when `volume` is also specified.
- **`status` output modes**: With `JOB_ID` shows single job; without shows all jobs.
- **`ssh` requires running job**: Job must be RUNNING with pod_id and exposed SSH host.
- **`workdir` path resolution**: Relative `workdir` paths are resolved to absolute paths based on the current working directory.
- **Stale key warnings**: Older documentation or examples may reference deprecated keys. These keys are ignored and should not be used.
- **For detailed workflows**: See [examples/local/README.md](../examples/local/README.md) and [examples/runpod/README.md](../examples/runpod/README.md).
