# Local Example: Two Jobs (Submitted in Order, Polled Together)

This example demonstrates submitting two jobs to the local provider using `pxq`, then polling both jobs until they complete.

## Overview

The example consists of:
- `job1_sleep_hello.py` - A Python job that sleeps for 3 seconds and prints "hello from local job1"
- `job2_sleep_hello.py` - A Python job that sleeps for 5 seconds and prints "hello from local job2"
- `run_two_jobs.sh` - A bash script that submits both jobs (in order) and monitors both until they reach a terminal status

## Prerequisites

Before running this example, ensure you have:

1. **pxq installed** - Already installed if you followed the main README
2. **Server running** - The pxq server must be running to process jobs
3. **python3** - Available on your PATH
4. **jq** - Command-line JSON processor (required by `run_two_jobs.sh`)

### Verify Dependencies

```bash
# Check pxq installation
pxq --help

# Check python
python3 --version

# Check jq
jq --version
```

## Quick Start

### Step 1: Start the Server

Open one terminal and start the pxq server:

```bash
pxq server
```

The server will start and display:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765
```

### Step 2: Execute the Example

Open a second terminal and run the example script:

```bash
bash examples/local/run_two_jobs.sh
```

### Step 3: Monitor Job Status

The script will:
1. Submit job 1
2. Submit job 2
3. Display both job IDs
4. Poll both jobs until both are in a terminal status

After the script finishes, you can confirm the final state:

```bash
pxq status --all
```

## Expected Results

Example output when successful:

```
Job IDs: 1 2
Checking job status...
[2s/300s] 1=running 2=queued
[4s/300s] 1=succeeded 2=running
[6s/300s] 1=succeeded 2=succeeded
[
  {
    "id": "1",
    "status": "succeeded",
    "provider": "local",
    "exit_code": 0,
    "command": "python3 examples/local/job1_sleep_hello.py"
  },
  {
    "id": "2",
    "status": "succeeded",
    "provider": "local",
    "exit_code": 0,
    "command": "python3 examples/local/job2_sleep_hello.py"
  }
]
```

Both jobs will eventually show `succeeded` status with exit code 0.

**Note**: This script does not print the jobs' stdout (the "hello from ..." lines) to your terminal. Use the dashboard or logs endpoint if you want to see job output.

## Troubleshooting

### Server Not Running

**Error**: Connection refused or "Server is not running"

**Solution**:
1. Ensure `pxq server` is running in a terminal
2. Check the server is running on the default port 8765
3. Try restarting the server with: `pxq server --port 8765`

### jq Not Found

**Error**: `jq: command not found`

**Solution**:
- Install jq on your system:
  - macOS: `brew install jq`
  - Ubuntu/Debian: `sudo apt-get install jq`
  - CentOS/RHEL: `sudo yum install jq`

### Job Submission Failed

**Error**: Job submission fails with connection errors

**Possible Causes**:
1. Server is not running
2. Server port is already in use
3. Database file permissions issue

**Solution**:
```bash
# Check if server is running
lsof -i :8765

# Restart the server
pkill pxq  # If running as background
pxq server
```

### Job Status Shows "Failed"

**Error**: Job status is `failed` or `error`

**Solution**:
1. Check individual job status:
   ```bash
   pxq status <JOB_ID>
   ```

2. Check job logs:
   ```bash
   curl http://127.0.0.1:8765/partials/jobs/<JOB_ID>/logs
   ```

3. Verify Python scripts are executable:
   ```bash
   chmod +x examples/local/job1_sleep_hello.py
   chmod +x examples/local/job2_sleep_hello.py
   ```

### Jobs Never Complete

**Possible Causes**:
1. Jobs taking longer than expected (though these examples only sleep a few seconds)
2. System resources exhausted
3. Server not responding

**Solution**:
1. Wait longer - jobs may be in "provisioning" or "running" state
2. Check system resources: `top` or `htop`
3. Restart the server: `pkill pxq && pxq server`

## Manual Job Execution

You can also execute jobs manually without the script:

### Run Job 1 Only

```bash
pxq add "python3 examples/local/job1_sleep_hello.py"
```

### Run Job 2 Only

```bash
pxq add "python3 examples/local/job2_sleep_hello.py"
```

### Monitor a Specific Job

```bash
pxq status <JOB_ID>
```

## Dashboard

You can also monitor jobs via the web dashboard:

1. Open a browser and navigate to: http://127.0.0.1:8765/
2. See real-time job status and logs
3. Refresh automatically every 10 seconds

## Files

- `job1_sleep_hello.py` - First job script
- `job2_sleep_hello.py` - Second job script
- `run_two_jobs.sh` - Submits two jobs and polls both to completion

## License

MIT
