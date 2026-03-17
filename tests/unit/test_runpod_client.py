"""Tests for RunPod API client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from pxq.providers.runpod_client import (
    ComputeType,
    PodCreateRequest,
    PodCreateRequest,
    PodMachine,
    PodResponse,
    PodStatus,
    RunPodAPIError,
    RunPodClient,
    RunPodRateLimitError,
)


class TestPodStatus:
    """Tests for PodStatus enum."""

    def test_is_terminal(self) -> None:
        """Test terminal status detection."""
        assert PodStatus.is_terminal(PodStatus.STOPPED)
        assert PodStatus.is_terminal(PodStatus.EXITED)
        assert PodStatus.is_terminal(PodStatus.TERMINATED)
        assert PodStatus.is_terminal(PodStatus.ERROR)
        assert not PodStatus.is_terminal(PodStatus.RUNNING)
        assert not PodStatus.is_terminal(PodStatus.CREATED)

    def test_is_ready(self) -> None:
        """Test ready status detection."""
        assert PodStatus.is_ready(PodStatus.RUNNING)
        assert not PodStatus.is_ready(PodStatus.CREATED)
        assert not PodStatus.is_ready(PodStatus.STOPPED)


class TestPodResponse:
    """Tests for PodResponse model."""

    def test_ssh_host_from_machine(self) -> None:
        """Test SSH host extraction from machine."""
        pod = PodResponse(
            id="pod-123",
            machine=PodMachine(public_ip="192.168.1.1", port=22),
        )
        assert pod.ssh_host == "192.168.1.1"

    def test_ssh_host_none_without_machine(self) -> None:
        """Test SSH host is None without machine."""
        pod = PodResponse(id="pod-123")
        assert pod.ssh_host is None

    def test_ssh_port_from_machine(self) -> None:
        """Test SSH port extraction from machine."""
        pod = PodResponse(
            id="pod-123",
            machine=PodMachine(port=2222),
        )
        assert pod.ssh_port == 2222

    def test_ssh_port_default(self) -> None:
        """Test SSH port defaults to 22."""
        pod = PodResponse(id="pod-123")
        assert pod.ssh_port == 22


class TestRunPodClient:
    """Tests for RunPodClient."""

    @pytest.fixture
    def client(self) -> RunPodClient:
        """Create a RunPod client for testing."""
        return RunPodClient(api_key="test-api-key")

    @pytest.mark.asyncio
    async def test_create_pod_gpu_success(self, client: RunPodClient) -> None:
        """Test successful GPU pod creation via REST API."""
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-gpu-123",
                "name": "test-gpu-pod",
                "desiredStatus": "CREATED",
                "imageName": "runpod/pytorch:latest",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test-gpu-pod",
                image_name="runpod/pytorch:latest",
                compute_type=ComputeType.GPU,
                gpu_type_ids=["NVIDIA RTX 4090"],
                gpu_count=1,
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/v1/pods" in call_args[0][0]

            # Verify GPU payload
            payload = call_args[1]["json"]
            assert payload["computeType"] == "GPU"
            assert payload["gpuTypeIds"] == ["NVIDIA RTX 4090"]
            assert payload["gpuCount"] == 1
            assert "cpuFlavorIds" not in payload

            assert result.id == "pod-gpu-123"
            assert result.name == "test-gpu-pod"
            assert result.status == PodStatus.CREATED

    @pytest.mark.asyncio
    async def test_create_pod_cpu_success(self, client: RunPodClient) -> None:
        """Test successful CPU pod creation via REST API."""
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-cpu-456",
                "name": "test-cpu-pod",
                "desiredStatus": "CREATED",
                "imageName": "ubuntu:22.04",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test-cpu-pod",
                image_name="ubuntu:22.04",
                compute_type=ComputeType.CPU,
                cpu_flavor_ids=["cpu3c"],
                gpu_count=2,  # vcpuCount
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "/v1/pods" in call_args[0][0]

            # Verify CPU payload - minimal approach
            payload = call_args[1]["json"]
            assert payload["computeType"] == "CPU"
            assert payload["cpuFlavorIds"] == ["cpu3c"]
            # vcpuCount is omitted (uses RunPod default of 2)
            assert "vcpuCount" not in payload
            assert "gpuTypeIds" not in payload
            assert "gpuCount" not in payload

            assert result.id == "pod-cpu-456"
            assert result.name == "test-cpu-pod"
            assert result.status == PodStatus.CREATED

    @pytest.mark.asyncio
    async def test_get_pod_success(self, client: RunPodClient) -> None:
        """Test successful pod retrieval."""
        mock_response = httpx.Response(
            200,
            json={
                "data": {
                    "pod": {
                        "id": "pod-123",
                        "name": "test-pod",
                        "status": "RUNNING",
                        "machine": {
                            "publicIp": "192.168.1.1",
                            "port": 2222,
                        },
                    }
                }
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            result = await client.get_pod("pod-123")

            assert result.id == "pod-123"
            assert result.status == PodStatus.RUNNING
            assert result.ssh_host == "192.168.1.1"
            assert result.ssh_port == 2222

    @pytest.mark.asyncio
    async def test_stop_pod_success(self, client: RunPodClient) -> None:
        """Test successful pod stop."""
        mock_response = httpx.Response(
            200,
            json={
                "data": {
                    "podStop": {
                        "id": "pod-123",
                        "status": "STOPPED",
                    }
                }
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            result = await client.stop_pod("pod-123")

            assert result.id == "pod-123"
            assert result.status == PodStatus.STOPPED

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, client: RunPodClient) -> None:
        """Test rate limit error handling for create_pod."""
        mock_response = httpx.Response(429, text="Rate limit exceeded")

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test",
                image_name="test",
                compute_type=ComputeType.CPU,
            )

            with pytest.raises(RunPodRateLimitError):
                await client.create_pod(request)

    @pytest.mark.asyncio
    async def test_api_error(self, client: RunPodClient) -> None:
        """Test API error handling for create_pod."""
        mock_response = httpx.Response(500, text="Internal server error")

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test",
                image_name="test",
                compute_type=ComputeType.CPU,
            )

            with pytest.raises(RunPodAPIError) as exc_info:
                await client.create_pod(request)

            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_pod_error(self, client: RunPodClient) -> None:
        """Test error handling for get_pod."""
        mock_response = httpx.Response(
            200,
            json={
                "errors": [{"message": "Pod not found"}],
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            with pytest.raises(RunPodAPIError) as exc_info:
                await client.get_pod("nonexistent")

            assert "Pod not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_env_passthrough_direct_env_no_template(
        self, client: RunPodClient
    ) -> None:
        """
        Test that direct env (without template_id) is passed to payload unchanged.

        This test ensures RunPod secret placeholders like {{ RUNPOD_SECRET_* }}
        are passed verbatim to the REST API without any modification.
        Regression test to prevent future env rewriting.
        """
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-env-123",
                "name": "test-env-pod",
                "desiredStatus": "CREATED",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            # Use realistic RunPod secret placeholders
            request = PodCreateRequest(
                name="test-env-pod",
                image_name="runpod/pytorch:latest",
                compute_type=ComputeType.GPU,
                gpu_type_ids=["NVIDIA RTX 4090"],
                gpu_count=1,
                env={
                    "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
                    "DATABASE_URL": "{{ RUNPOD_SECRET_DATABASE_URL }}",
                    "API_TOKEN": "{{ RUNPOD_SECRET_API_TOKEN }}",
                },
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1]["json"]

            # CRITICAL: payload["env"] must match request.env exactly
            # No rewriting, no synthetic defaults, no overwrites
            assert payload["env"] == request.env
            assert payload["env"]["KAGGLE_KEY"] == "{{ RUNPOD_SECRET_KAGGLE_KEY }}"
            assert payload["env"]["DATABASE_URL"] == "{{ RUNPOD_SECRET_DATABASE_URL }}"
            assert payload["env"]["API_TOKEN"] == "{{ RUNPOD_SECRET_API_TOKEN }}"

            assert result.id == "pod-env-123"

    @pytest.mark.asyncio
    async def test_env_with_template_id_includes_env(
        self, client: RunPodClient
    ) -> None:
        """
        Test that env IS included even when template_id is set.

        CURRENT BEHAVIOR (lines 451-452 in runpod_client.py):
        - The code has two conditional blocks for env handling
        - Lines 443-444 check `if request.env and not request.template_id`
        - Lines 451-452 check `if request.env` (unconditional on template_id)
        - The second block overrides the first, so env IS included with template_id

        This test documents the ACTUAL behavior, not the commented intent.
        The comment "Only include env if not using template" is INCORRECT.
        """
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-template-123",
                "name": "test-template-pod",
                "desiredStatus": "CREATED",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test-template-pod",
                image_name="runpod/pytorch:latest",  # Required even with template
                template_id="tpl-abc123",
                compute_type=ComputeType.GPU,
                gpu_type_ids=["NVIDIA RTX 4090"],
                gpu_count=1,
                env={
                    "OVERRIDE_VAR": "custom-value",
                    "SECRET_KEY": "{{ RUNPOD_SECRET_KEY }}",
                },
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1]["json"]

            # CURRENT BEHAVIOR: env IS included even with template_id
            # This is because lines 451-452 unconditionally set payload["env"] if request.env exists
            assert payload["templateId"] == "tpl-abc123"
            assert payload["env"] == request.env
            assert payload["env"]["OVERRIDE_VAR"] == "custom-value"
            assert payload["env"]["SECRET_KEY"] == "{{ RUNPOD_SECRET_KEY }}"

            assert result.id == "pod-template-123"

    @pytest.mark.asyncio
    async def test_env_none_no_synthetic_defaults(self, client: RunPodClient) -> None:
        """
        Test that env=None does not create synthetic defaults.

        Regression test: ensure no synthetic env dict is created when env is None.
        """
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-noenv-123",
                "name": "test-noenv-pod",
                "desiredStatus": "CREATED",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test-noenv-pod",
                image_name="runpod/pytorch:latest",
                compute_type=ComputeType.GPU,
                gpu_type_ids=["NVIDIA RTX 4090"],
                gpu_count=1,
                env=None,  # Explicitly None
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1]["json"]

            # env=None should NOT create a synthetic dict
            assert "env" not in payload

            assert result.id == "pod-noenv-123"

    @pytest.mark.asyncio
    async def test_professional_gpu_rtx2000ada_payload(
        self, client: RunPodClient
    ) -> None:
        """Test that professional GPU RTX2000Ada serializes to REST payload.

        Regression test: ensures professional GPU type ID is serialized
        exactly as-is to the REST API payload (no modification).
        """
        mock_response = httpx.Response(
            200,
            json={
                "id": "pod-prof-gpu-rest-001",
                "name": "test-prof-gpu-rest-pod",
                "desiredStatus": "CREATED",
                "imageName": "runpod/pytorch:latest",
            },
        )

        with patch.object(
            httpx.AsyncClient, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = mock_response

            request = PodCreateRequest(
                name="test-prof-gpu-rest-pod",
                image_name="runpod/pytorch:latest",
                compute_type=ComputeType.GPU,
                gpu_type_ids=["NVIDIA RTX 2000 Ada Generation"],  # Professional GPU ID
                gpu_count=2,
            )
            result = await client.create_pod(request)

            # Verify REST API was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args

            # Verify payload contains exact GPU type ID (professional)
            payload = call_args[1]["json"]
            assert payload["computeType"] == "GPU"
            assert payload["gpuTypeIds"] == ["NVIDIA RTX 2000 Ada Generation"]
            assert payload["gpuCount"] == 2

            assert result.id == "pod-prof-gpu-rest-001"
            assert result.name == "test-prof-gpu-rest-pod"
            assert result.status == PodStatus.CREATED
