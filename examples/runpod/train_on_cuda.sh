set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
pxq add "nvidia-smi && pwd && ls && pip install -r requirements.txt && python train_model.py" --config config/torch-cuda-with-volume.yaml
