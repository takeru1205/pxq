"""RunPod GPU type resolver.

Provides static mapping from pxq CLI GPU type strings to RunPod GPU IDs.
"""

from __future__ import annotations

# Static mapping from pxq CLI type to RunPod GPU ID
# Source: docs/GPUs.md and runpod_openapi.json
GPU_TYPE_MAPPING: dict[str, str] = {
    # Consumer GPUs (GeForce RTX Series)
    "RTX3070": "NVIDIA GeForce RTX 3070",
    "RTX3080": "NVIDIA GeForce RTX 3080",
    "RTX3080Ti": "NVIDIA GeForce RTX 3080 Ti",
    "RTX3090": "NVIDIA GeForce RTX 3090",
    "RTX3090Ti": "NVIDIA GeForce RTX 3090 Ti",
    "RTX4070Ti": "NVIDIA GeForce RTX 4070 Ti",
    "RTX4080": "NVIDIA GeForce RTX 4080",
    "RTX4080SUPER": "NVIDIA GeForce RTX 4080 SUPER",
    "RTX4090": "NVIDIA GeForce RTX 4090",
    "RTX5080": "NVIDIA GeForce RTX 5080",
    "RTX5090": "NVIDIA GeForce RTX 5090",
    # Data Center GPUs - Ampere Architecture
    "A30": "NVIDIA A30",
    "A40": "NVIDIA A40",
    "A100PCIe": "NVIDIA A100 80GB PCIe",
    "A100SXM": "NVIDIA A100-SXM4-80GB",
    # Data Center GPUs - Hopper Architecture
    "H100PCIe": "NVIDIA H100 PCIe",
    "H100SXM": "NVIDIA H100 80GB HBM3",
    "H100NVL": "NVIDIA H100 NVL",
    "H200SXM": "NVIDIA H200",
    "H200NVL": "NVIDIA H200 NVL",
    # Data Center GPUs - Blackwell Architecture
    "B200": "NVIDIA B200",
    "B300": "NVIDIA B300 SXM6 AC",
    # Data Center GPUs - Ada Lovelace Architecture
    "L4": "NVIDIA L4",
    "L40": "NVIDIA L40",
    "L40S": "NVIDIA L40S",
    # Professional GPUs (RTX Ada/Ampere Series)
    "RTX2000Ada": "NVIDIA RTX 2000 Ada Generation",
    "RTX4000Ada": "NVIDIA RTX 4000 Ada Generation",
    "RTX4000AdaSFF": "NVIDIA RTX 4000 SFF Ada Generation",
    "RTX5000Ada": "NVIDIA RTX 5000 Ada Generation",
    "RTX6000Ada": "NVIDIA RTX 6000 Ada Generation",
    "RTXA2000": "NVIDIA RTX A2000",
    "RTXA4000": "NVIDIA RTX A4000",
    "RTXA4500": "NVIDIA RTX A4500",
    "RTXA5000": "NVIDIA RTX A5000",
    "RTXA6000": "NVIDIA RTX A6000",
    # Blackwell Professional GPUs
    "RTXPRO4500": "NVIDIA RTX PRO 4500 Blackwell",
    "RTXPRO6000": "NVIDIA RTX PRO 6000 Blackwell Server Edition",
    "RTXPRO6000MaxQ": "NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition",
    "RTXPRO6000WK": "NVIDIA RTX PRO 6000 Blackwell Workstation Edition",
}


def resolve_gpu_type(gpu_spec: str) -> tuple[list[str], int]:
    """Resolve a GPU specification to RunPod GPU type IDs and count.

    Args:
        gpu_spec: GPU specification in format "<gpu_name>[:count]"
                  e.g., "RTX4090", "RTX2000Ada:2", "A100SXM:4"

    Returns:
        Tuple of (gpu_type_ids, gpu_count) where gpu_type_ids is a list
        containing the RunPod GPU ID string.

    Raises:
        ValueError: If GPU name is not supported or count is invalid.
    """
    parts = gpu_spec.split(":")
    gpu_name = parts[0]

    # Parse count (default to 1 if not specified)
    if len(parts) > 1:
        try:
            gpu_count = int(parts[1])
        except ValueError:
            raise ValueError(f"Invalid GPU count: {parts[1]}") from None
        if gpu_count < 1:
            raise ValueError(f"GPU count must be >= 1, got: {gpu_count}")
    else:
        gpu_count = 1

    # Look up GPU type ID
    if gpu_name not in GPU_TYPE_MAPPING:
        raise ValueError(f"Unsupported RunPod GPU type: {gpu_name}")

    gpu_type_id = GPU_TYPE_MAPPING[gpu_name]
    return [gpu_type_id], gpu_count
