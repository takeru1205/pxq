# RunPod Example: Kaggle Space Titanic with pxq

This guide demonstrates how to use `pxq` to run a two-stage ML workflow on RunPod:

1. **CPU Pod**: Download Kaggle Space Titanic dataset to Network Volume
2. **GPU Pod**: Train PyTorch model using the downloaded data

## Prerequisites

### 1. Create a Network Volume in RunPod

Create a Network Volume in the RunPod console before starting:

- **Volume ID**: `da06u1of66` (or your own volume ID)
- **Region**: EU-RO-1
- **Size**: At least 10GB recommended

**Note**: This guide assumes the volume is already created.

### 2. Configure Kaggle API Credentials

Set Kaggle credentials as RunPod Secrets in the RunPod console:

1. Go to RunPod Console → Settings → Secrets
2. Add the following secrets:
   - `RUNPOD_SECRET_KAGGLE_USERNAME`: Your Kaggle username
   - `RUNPOD_SECRET_KAGGLE_KEY`: Your Kaggle API key

Get your Kaggle API key from: https://www.kaggle.com/settings

### 3. Install pxq

```bash
# Install directly from GitHub (recommended, no clone required)
uv tool install git+https://github.com/takeru1205/pxq.git

# Or install from source (for development)
git clone https://github.com/takeru1205/pxq.git
cd pxq
uv tool install -e .

# Verify installation
pxq --help
```

### 4. Set RunPod API Key

```bash
export PXQ_RUNPOD_API_KEY="your_runpod_api_key"
```

### 5. Start pxq Server

```bash
pxq server
```

## Quick Start

### Step 1: Download Dataset to Volume (CPU Pod)

```bash
# Submit download job
DOWNLOAD_JSON=$(pxq add "pip install kaggle && python3 download_dataset.py" \
  --provider runpod \
  --cpu \
  --volume da06u1of66 \
  --managed \
  --region EU-RO-1)

echo "$DOWNLOAD_JSON"
DOWNLOAD_JOB_ID=$(echo "$DOWNLOAD_JSON" | jq -r '.id')
echo "Download Job ID: $DOWNLOAD_JOB_ID"
```

**What this does:**
- Creates a CPU-only pod (cost-effective for download)
- Mounts the Network Volume at `/volume`
- Downloads Space Titanic dataset to `/volume/data/spaceship-titanic/`
- Automatically stops the pod after completion (managed mode)

**Monitor download progress:**
```bash
pxq status $DOWNLOAD_JOB_ID
```

**Expected status flow:**
```
queued -> provisioning -> uploading -> running -> succeeded -> stopped
```

### Step 2: Train Model on GPU (GPU Pod)

After the download job completes successfully:

```bash
# Submit training job
TRAIN_JSON=$(pxq add "python3 train_model.py" \
  --provider runpod \
  --gpu RTX4090:1 \
  --volume da06u1of66 \
  --managed \
  --region EU-RO-1)

echo "$TRAIN_JSON"
TRAIN_JOB_ID=$(echo "$TRAIN_JSON" | jq -r '.id')
echo "Training Job ID: $TRAIN_JOB_ID"
```

**What this does:**
- Creates a GPU pod with RTX4090:1 in EU-RO-1 region
- Mounts the Network Volume at `/volume`
- Loads data from `/volume/data/spaceship-titanic/`
- Uses 20% of data for training (as specified in the script)
- Saves metrics to `/volume/results/metrics.json`
- Automatically stops the pod after completion

**Monitor training progress:**
```bash
pxq status $TRAIN_JOB_ID
```

### Step 3: View Results

After training completes:

```bash
# Check job status and exit code
pxq status $TRAIN_JOB_ID | jq '.status, .exit_code'

# View metrics (requires SSH to pod or download from volume)
# The metrics are saved to /volume/results/metrics.json
```

**Example metrics output:**
```json
{
  "epochs": 50,
  "batch_size": 32,
  "learning_rate": 0.001,
  "best_val_accuracy": 0.7852,
  "final_train_accuracy": 0.7923,
  "final_val_accuracy": 0.7801,
  "training_time_seconds": 15.3,
  "device": "cuda",
  "dataset": "spaceship-titanic",
  "sample_ratio": 0.2,
  "train_samples": 1306,
  "val_samples": 327,
  "num_features": 10
}
```

## Volume Data Structure

After both jobs complete, your volume will contain:

```
/volume/
├── data/
│   └── spaceship-titanic/
│       ├── train.csv
│       ├── test.csv
│       └── sample_submission.csv
└── results/
    └── metrics.json
```

## Configuration Options

### GPU Types

Available GPU options in EU-RO-1:

```bash
# High-end GPU (recommended)
pxq add "python3 train_model.py" --gpu RTX4090:1 --volume da06u1of66

# Mid-range GPU
pxq add "python3 train_model.py" --gpu RTX3080:1 --volume da06u1of66

# Budget GPU
pxq add "python3 train_model.py" --gpu RTX3070:1 --volume da06u1of66
```

### Custom Volume Mount Path

By default, volumes are mounted at `/volume`. To use a custom path:

```bash
pxq add "python3 train_model.py" \
  --volume da06u1of66 \
  --volume-path /mnt/data
```

Note: If you use a custom mount path, update the scripts to use the new path.

### Non-Managed Mode

To keep the pod running after job completion:

```bash
pxq add "python3 train_model.py" --volume da06u1of66  # Without --managed
```

## Troubleshooting

### GPU/CPU Capacity Issues

**Symptom**: `GraphQL error: There are no longer any instances available` or `This machine does not have the resources`

**Cause**: RunPod community cloud has limited capacity, especially for specific GPU types and regions.

**Solutions**:
1. **Try different GPU types**: RTX3070, RTX3080, RTX3090, RTX4070, RTX4080, RTX4090
2. **Try different regions**: Remove `--region` to let RunPod auto-select, or try NA/AS regions
3. **Retry after delay**: Capacity fluctuates; wait 5-10 minutes and retry
4. **Check RunPod Console**: Verify available instances at https://console.runpod.io/
5. **Use secure cloud**: Community cloud may be full; secure cloud has more capacity (higher cost)

**Example with different GPU**:
```bash
pxq add "python3 download_dataset.py" --gpu RTX4090:1 --volume da06u1of66 --managed
```

### Download Job Fails

**Symptom**: Job status shows `failed` with Kaggle authentication error

**Solution**:
1. Verify Kaggle secrets are set in RunPod Console
2. Check secret names: `RUNPOD_SECRET_KAGGLE_USERNAME` and `RUNPOD_SECRET_KAGGLE_KEY`
3. Retry the download job

### Training Job Cannot Find Data

**Symptom**: `Error: Data directory not found: /volume/data/spaceship-titanic`

**Solution**:
1. Verify download job completed successfully: `pxq status $DOWNLOAD_JOB_ID`
2. Confirm both jobs use the same `--volume` ID
3. Check volume region matches pod region (EU-RO-1)

### GPU Pod Fails to Provision

**Symptom**: Job stuck in `provisioning` or fails with GPU unavailable

**Solution**:
1. Try a different GPU type (e.g., RTX3080:1 instead of RTX4090:1)
2. Check GPU availability in EU-RO-1 region
3. Retry after a few minutes

### Volume Mount Issues

**Symptom**: Pod cannot access volume data

**Solution**:
1. Verify volume ID is correct
2. Confirm volume is in the same region as the pod (EU-RO-1)
3. Check volume is not attached to another running pod

## Cost Estimation

Approximate costs for this workflow (using RunPod pricing):

| Stage | Pod Type | Duration | Cost |
|-------|----------|----------|------|
| Download | CPU | ~5 min | ~$0.01 |
| Training | RTX4090:1 | ~10 min | ~$0.07 |
| **Total** | | | **~$0.08** |

Both pods are automatically stopped after completion (managed mode), so you only pay for actual usage.

## Scripts Reference

### download_dataset.py

Downloads Kaggle Space Titanic dataset to `/volume/data/spaceship-titanic/`.

**Features:**
- Uses Kaggle CLI for download
- Creates necessary directories
- Verifies downloaded files
- Requires Kaggle API credentials as RunPod secrets

### train_model.py

Trains a PyTorch classifier on the downloaded dataset.

**Features:**
- Uses 20% of data (configurable via `sample_ratio`)
- Simple feedforward neural network
- Saves metrics to `/volume/results/metrics.json`
- Reports GPU/CPU device used

**Configuration:**
- Epochs: 50
- Batch size: 32
- Learning rate: 0.001
- Sample ratio: 20%

## Next Steps

After completing this tutorial:

1. **Experiment with hyperparameters**: Modify `train_model.py` to adjust epochs, learning rate, etc.
2. **Use more data**: Increase `sample_ratio` from 0.2 to 1.0 for full dataset
3. **Try different models**: Implement more sophisticated architectures
4. **Submit predictions**: Use the trained model for Kaggle submission

## Related Resources

- [pxq Documentation](../../README.md)
- [RunPod Documentation](https://docs.runpod.io/)
- [Kaggle Space Titanic Dataset](https://www.kaggle.com/datasets/yanama/spaceship-titanic)
- [PyTorch Documentation](https://pytorch.org/docs/)

## Using RunPod Secrets (Direct or via Template)

pxq supports RunPod Secrets in two ways:

### Option 1: Direct env in Config File (No Template Required)

You can use RunPod Secrets directly by specifying env variables with `{{ RUNPOD_SECRET_* }}` placeholders in a YAML config file:

```yaml
# config.yaml
provider: runpod
cpu: true
cpu_flavor_ids:
  - cpu3c
managed: true
region: EU-RO-1
volume: da06u1of66
env:
  KAGGLE_KEY: "{{ RUNPOD_SECRET_KAGGLE_KEY }}"
  KAGGLE_USERNAME: "{{ RUNPOD_SECRET_KAGGLE_USERNAME }}"
```

Then run:
```bash
pxq add "pip install kaggle && python3 download_dataset.py" --config config.yaml
```

pxq passes the env values (including secret placeholders) directly to RunPod's POST /v1/pods API. RunPod expands the `{{ RUNPOD_SECRET_* }}` placeholders server-side when the pod starts.

**Note**: Secret placeholders work WITHOUT templates. Templates are only for reusing complete pod configurations.

### Option 2: Using Templates for Reuse (Optional)

For frequently-used configurations, you can create a RunPod Template that includes environment variables with secret placeholders.

#### Step 1: Create Template
## Using RunPod Template (Recommended for Secrets)

When using RunPod Secrets, create a Template first:

### Step 1: Create Template

1. Go to https://www.runpod.io/console/user/templates
2. Click "Create Template"
3. Fill in:
   - **Name**: `pxq-cpu-job`
   - **Description**: Template for pxq CPU jobs with Kaggle secrets
   - **Image**: `runpod/base:1.0.2-ubuntu2204`
   - **Container Disk**: `20 GB`
   - **Ports**: `22/tcp`
4. Add Environment Variables:
   - `KAGGLE_KEY` = `{{ RUNPOD_SECRET_KAGGLE_KEY }}`
   - `KAGGLE_USERNAME` = `{{ RUNPOD_SECRET_KAGGLE_USERNAME }}`
5. Click "Save"
6. Copy the Template ID (e.g., `abc123xyz`)

### Step 2: Run with Template

```bash
# Step 1: Download dataset using Template
DOWNLOAD_JSON=$(pxq add "pip install kaggle && python3 download_dataset.py" \
  --provider runpod \
  --template <YOUR_TEMPLATE_ID> \
  --cpu \
  --cpu-flavor cpu3c \
  --secure-cloud \
  --volume da06u1of66 \
  --managed \
  --region EU-RO-1)

# Poll until job completes

while true; do STATUS=$(pxq status $DOWNLOAD_JOB_ID | jq -r '.status'); echo "Status: $STATUS"; [[ "$STATUS" == "succeeded" || "$STATUS" == "failed" || "$STATUS" == "stopped" ]] && break; sleep 5; done

# Step 2: Train model using Template
TRAIN_JSON=$(pxq add "python3 train_model.py" \
  --provider runpod \
  --template <YOUR_TEMPLATE_ID> \
  --gpu RTX4090:1 \
  --secure-cloud \
  --volume da06u1of66 \
  --managed \
  --region EU-RO-1)

# Poll until job completes

while true; do STATUS=$(pxq status $TRAIN_JOB_ID | jq -r '.status'); echo "Status: $STATUS"; [[ "$STATUS" == "succeeded" || "$STATUS" == "failed" || "$STATUS" == "stopped" ]] && break; sleep 5; done

```

**Note**: When using `--template`, environment variables are defined in the Template, not in the CLI.
