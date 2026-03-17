"""Tests for RunPod GPU type resolver."""

import pytest

from pxq.providers.runpod_gpu_types import GPU_TYPE_MAPPING, resolve_gpu_type


class TestResolveGpuType:
    """Tests for resolve_gpu_type function."""

    def test_rtx2000ada_with_count(self) -> None:
        """Test RTX2000Ada:2 parsing."""
        gpu_type_ids, gpu_count = resolve_gpu_type("RTX2000Ada:2")
        assert gpu_type_ids == ["NVIDIA RTX 2000 Ada Generation"]
        assert gpu_count == 2

    def test_rtx4090_with_count(self) -> None:
        """Test RTX4090:1 parsing."""
        gpu_type_ids, gpu_count = resolve_gpu_type("RTX4090:1")
        assert gpu_type_ids == ["NVIDIA GeForce RTX 4090"]
        assert gpu_count == 1

    def test_rtx4090_no_count(self) -> None:
        """Test RTX4090 without count (defaults to 1)."""
        gpu_type_ids, gpu_count = resolve_gpu_type("RTX4090")
        assert gpu_type_ids == ["NVIDIA GeForce RTX 4090"]
        assert gpu_count == 1

    def test_invalid_gpu_type(self) -> None:
        """Test unsupported GPU type raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported RunPod GPU type: InvalidGPU"):
            resolve_gpu_type("InvalidGPU")

    def test_invalid_count_zero(self) -> None:
        """Test count of 0 raises ValueError."""
        with pytest.raises(ValueError, match="GPU count must be >= 1"):
            resolve_gpu_type("RTX4090:0")

    def test_invalid_count_negative(self) -> None:
        """Test negative count raises ValueError."""
        with pytest.raises(ValueError, match="GPU count must be >= 1"):
            resolve_gpu_type("RTX4090:-1")

    def test_invalid_count_non_numeric(self) -> None:
        """Test non-numeric count raises ValueError."""
        with pytest.raises(ValueError, match="Invalid GPU count"):
            resolve_gpu_type("RTX4090:abc")

    def test_all_gpus_in_mapping(self) -> None:
        """Test that all GPUs in mapping can be resolved."""
        for gpu_name, expected_id in GPU_TYPE_MAPPING.items():
            gpu_type_ids, gpu_count = resolve_gpu_type(gpu_name)
            assert gpu_type_ids == [expected_id]
            assert gpu_count == 1

    def test_a100sxm(self) -> None:
        """Test A100SXM parsing (data center GPU)."""
        gpu_type_ids, gpu_count = resolve_gpu_type("A100SXM")
        assert gpu_type_ids == ["NVIDIA A100-SXM4-80GB"]
        assert gpu_count == 1

    def test_h100sxm_with_count(self) -> None:
        """Test H100SXM:4 parsing."""
        gpu_type_ids, gpu_count = resolve_gpu_type("H100SXM:4")
        assert gpu_type_ids == ["NVIDIA H100 80GB HBM3"]
        assert gpu_count == 4
