# GPU Types Reference

This document provides a mapping between pxq CLI GPU type strings and RunPod GPU identifiers.

## GPU Type Format

pxq uses a simple GPU type format: `GPU_NAME:COUNT`

- **GPU_NAME**: Short GPU identifier (e.g., `RTX4090`, `A100`, `H100`)
- **COUNT**: Number of GPUs (optional, defaults to 1)

Example:
```bash
pxq add "python train.py" --provider runpod --gpu "RTX4090:2"
```

## Consumer GPUs (GeForce RTX Series)

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| RTX3070 | NVIDIA GeForce RTX 3070 | RTX 3070 | 8 GB |
| RTX3080 | NVIDIA GeForce RTX 3080 | RTX 3080 | 10 GB |
| RTX3080Ti | NVIDIA GeForce RTX 3080 Ti | RTX 3080 Ti | 12 GB |
| RTX3090 | NVIDIA GeForce RTX 3090 | RTX 3090 | 24 GB |
| RTX3090Ti | NVIDIA GeForce RTX 3090 Ti | RTX 3090 Ti | 24 GB |
| RTX4070Ti | NVIDIA GeForce RTX 4070 Ti | RTX 4070 Ti | 12 GB |
| RTX4080 | NVIDIA GeForce RTX 4080 | RTX 4080 | 16 GB |
| RTX4080SUPER | NVIDIA GeForce RTX 4080 SUPER | RTX 4080 SUPER | 16 GB |
| RTX4090 | NVIDIA GeForce RTX 4090 | RTX 4090 | 24 GB |
| RTX5080 | NVIDIA GeForce RTX 5080 | RTX 5080 | 16 GB |
| RTX5090 | NVIDIA GeForce RTX 5090 | RTX 5090 | 32 GB |

## Data Center GPUs (NVIDIA)

### Ampere Architecture

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| A30 | NVIDIA A30 | A30 | 24 GB |
| A40 | NVIDIA A40 | A40 | 48 GB |
| A100PCIe | NVIDIA A100 80GB PCIe | A100 PCIe | 80 GB |
| A100SXM | NVIDIA A100-SXM4-80GB | A100 SXM | 80 GB |

### Hopper Architecture

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| H100PCIe | NVIDIA H100 PCIe | H100 PCIe | 80 GB |
| H100SXM | NVIDIA H100 80GB HBM3 | H100 SXM | 80 GB |
| H100NVL | NVIDIA H100 NVL | H100 NVL | 94 GB |
| H200SXM | NVIDIA H200 | H200 SXM | 141 GB |
| H200NVL | NVIDIA H200 NVL | NVIDIA H200 NVL | 143 GB |

### Blackwell Architecture

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| B200 | NVIDIA B200 | B200 | 180 GB |
| B300 | NVIDIA B300 SXM6 AC | B300 | 288 GB |

### Ada Lovelace Architecture

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| L4 | NVIDIA L4 | L4 | 24 GB |
| L40 | NVIDIA L40 | L40 | 48 GB |
| L40S | NVIDIA L40S | L40S | 48 GB |

## Professional GPUs (RTX Ada/Ampere Series)

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| RTX2000Ada | NVIDIA RTX 2000 Ada Generation | RTX 2000 Ada | 16 GB |
| RTX4000Ada | NVIDIA RTX 4000 Ada Generation | RTX 4000 Ada | 20 GB |
| RTX4000AdaSFF | NVIDIA RTX 4000 SFF Ada Generation | RTX 4000 Ada SFF | 20 GB |
| RTX5000Ada | NVIDIA RTX 5000 Ada Generation | RTX 5000 Ada | 32 GB |
| RTX6000Ada | NVIDIA RTX 6000 Ada Generation | RTX 6000 Ada | 48 GB |
| RTXA2000 | NVIDIA RTX A2000 | RTX A2000 | 6 GB |
| RTXA4000 | NVIDIA RTX A4000 | RTX A4000 | 16 GB |
| RTXA4500 | NVIDIA RTX A4500 | RTX A4500 | 20 GB |
| RTXA5000 | NVIDIA RTX A5000 | RTX A5000 | 24 GB |
| RTXA6000 | NVIDIA RTX A6000 | RTX A6000 | 48 GB |

## Blackwell Professional GPUs

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| RTXPRO4500 | NVIDIA RTX PRO 4500 Blackwell | RTX PRO 4500 | 32 GB |
| RTXPRO6000 | NVIDIA RTX PRO 6000 Blackwell Server Edition | RTX PRO 6000 | 96 GB |
| RTXPRO6000MaxQ | NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition | RTX PRO 6000 MaxQ | 96 GB |
| RTXPRO6000WK | NVIDIA RTX PRO 6000 Blackwell Workstation Edition | RTX PRO 6000 WK | 96 GB |

## Legacy GPUs (Volta Architecture)

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| V100 | Tesla V100-PCIE-16GB | Tesla V100 | 16 GB |
| V100SXM2 | Tesla V100-SXM2-16GB | V100 SXM2 | 16 GB |
| V100SXM232GB | Tesla V100-SXM2-32GB | V100 SXM2 32GB | 32 GB |

## AMD GPUs

| pxq CLI Type | RunPod GPU ID | Display Name | Memory |
|--------------|---------------|--------------|--------|
| MI300X | AMD Instinct MI300X OAM | MI300X | 192 GB |

## GPU Pools

RunPod provides GPU pools for flexible GPU allocation. These are used for Hub endpoints and API specifications:

| Pool ID | GPUs Included | Memory |
|---------|---------------|--------|
| AMPERE_16 | A4000, A4500, RTX 4000, RTX 2000 | 16 GB |
| AMPERE_24 | L4, A5000, 3090 | 24 GB |
| ADA_24 | 4090 | 24 GB |
| AMPERE_48 | A6000, A40 | 48 GB |
| ADA_48_PRO | L40, L40S, 6000 Ada | 48 GB |
| AMPERE_80 | A100 | 80 GB |
| ADA_80_PRO | H100 | 80 GB |
| HOPPER_141 | H200 | 141 GB |

## Usage Examples

### Single GPU Job

```bash
pxq add "python train.py" --provider runpod --gpu "RTX4090:1"
```

### Multi-GPU Job

```bash
pxq add "torchrun --nproc_per_node=4 train.py" --provider runpod --gpu "A100SXM:4"
```

### Using Config File

```yaml
# config.yaml
provider: runpod
gpu_type: RTX4090:1
managed: true
```

```bash
pxq add "python train.py" --config config.yaml
```

## Notes

- GPU availability varies by region and cloud type (Community vs Secure Cloud)
- For pricing information, see [RunPod GPU Pricing](https://www.runpod.io/gpu-instance/pricing)
- Some GPUs may only be available in Secure Cloud
- The `--gpu` and `--cpu` options are mutually exclusive

## References

- [RunPod GPU Types Documentation](https://docs.runpod.io/references/gpu-types)
- [RunPod GPU Models](https://www.runpod.io/gpu-models)