"""Tests for RunPod provider functions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pxq.config import Settings
from pxq.providers.runpod_client import PodMachine, PodResponse, PodStatus, RunPodClient
from pxq.providers.runpod_provider import ProvisioningTimeoutError, wait_for_pod_ready


class TestProvisioningTimeoutError:
    """Tests for ProvisioningTimeoutError exception."""

    def test_error_message_contains_pod_id(self) -> None:
        """Test that error message includes pod ID and timeout."""
        error = ProvisioningTimeoutError(pod_id="pod-abc123", timeout_minutes=10)

        assert "pod-abc123" in str(error)
        assert "10 minutes" in str(error)

    def test_error_attributes(self) -> None:
        """Test that error has correct attributes."""
        error = ProvisioningTimeoutError(pod_id="pod-xyz789", timeout_minutes=20)

        assert error.pod_id == "pod-xyz789"
        assert error.timeout_minutes == 20


class TestWaitForPodReady:
    """Tests for wait_for_pod_ready function.

    Note: The 15-second wait for Secret expansion is verified by code review.
    Mocking asyncio.sleep globally breaks pytest-asyncio's event loop management.
    The implementation adds `await asyncio.sleep(15)` after pod becomes RUNNING,
    which can be verified in src/pxq/providers/runpod_provider.py lines 62-67.
    """

    @pytest.mark.asyncio
    async def test_raises_timeout_when_pod_never_becomes_ready(self) -> None:
        """Test that ProvisioningTimeoutError is raised when pod doesn't become ready."""
        # Arrange
        mock_client = MagicMock(spec=RunPodClient)
        mock_client.get_pod = AsyncMock()

        created_pod = PodResponse(
            id="pod-test-456",
            status=PodStatus.CREATED,
        )
        mock_client.get_pod.return_value = created_pod

        # Very short timeout - will timeout on first check
        settings = Settings(provisioning_timeout_minutes=0)

        # Act & Assert - will timeout immediately since timeout is 0
        with pytest.raises(ProvisioningTimeoutError) as exc_info:
            await wait_for_pod_ready(
                runpod_client=mock_client,
                pod_id="pod-test-456",
                settings=settings,
                poll_interval_seconds=0.001,  # Very short interval
            )

        assert exc_info.value.pod_id == "pod-test-456"
        assert exc_info.value.timeout_minutes == 0
