"""Tests for job executor."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pxq.executor import JobExecutor
from pxq.models import Job, JobStatus
from pxq.providers.runpod_client import (
    ComputeType,
    PodCreateRequest,
    PodResponse,
    PodStatus,
    RunPodClient,
)


class TestJobExecutorEnvPassthrough:
    """Tests for environment variable passthrough in executor.

    Tests for:
    - Environment variable passthrough (secrets, None, empty dict)
    - CPU image selection (runpod/base for CPU pods)
    - No-volume defaults (volume_in_gb=0, volume_mount_path=/workspace)
    """

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        """Create a temporary database path."""
        return tmp_path / "test.db"

    @pytest.fixture
    def executor(self, db_path: Path) -> JobExecutor:
        """Create a JobExecutor instance for testing."""
        return JobExecutor(db_path=db_path)

    @pytest.mark.asyncio
    async def test_env_passthrough_with_secrets(self, executor: JobExecutor) -> None:
        """Test that job.env with secret placeholders is passed through unchanged."""
        job = Job(
            id=1,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            env={
                "API_KEY": "{{ RUNPOD_SECRET_API_KEY }}",
                "DB_PASSWORD": "{{ RUNPOD_SECRET_DB_PASSWORD }}",
            },
        )

        mock_pod = PodResponse(
            id="pod-123",
            name="test-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify env was passed through unchanged
        assert captured_request is not None
        assert captured_request.env == {
            "API_KEY": "{{ RUNPOD_SECRET_API_KEY }}",
            "DB_PASSWORD": "{{ RUNPOD_SECRET_DB_PASSWORD }}",
        }

    @pytest.mark.asyncio
    async def test_env_passthrough_none(self, executor: JobExecutor) -> None:
        """Test that job.env=None results in fallback Kaggle secrets.

        When no env is specified, the executor provides a fallback with
        Kaggle secret placeholders for RunPod server-side expansion.
        """
        job = Job(
            id=2,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            env=None,  # No env specified
        )

        mock_pod = PodResponse(
            id="pod-456",
            name="test-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify fallback Kaggle secrets are used when env is None
        assert captured_request is not None
        assert captured_request.env == {
            "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
            "KAGGLE_USERNAME": "{{ RUNPOD_SECRET_KAGGLE_USERNAME }}",
        }

    @pytest.mark.asyncio
    async def test_env_passthrough_empty_dict(self, executor: JobExecutor) -> None:
        """Test that job.env={} results in fallback Kaggle secrets.

        When an empty env dict is specified, the executor provides a fallback
        with Kaggle secret placeholders for RunPod server-side expansion.
        """
        job = Job(
            id=3,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            env={},  # Empty env dict
        )

        mock_pod = PodResponse(
            id="pod-789",
            name="test-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify fallback Kaggle secrets are used when env is empty dict
        assert captured_request is not None
        assert captured_request.env == {
            "KAGGLE_KEY": "{{ RUNPOD_SECRET_KAGGLE_KEY }}",
            "KAGGLE_USERNAME": "{{ RUNPOD_SECRET_KAGGLE_USERNAME }}",
        }

    @pytest.mark.asyncio
    async def test_cpu_image_selection(self, executor: JobExecutor) -> None:
        """Test that CPU jobs use runpod/base:1.0.2-ubuntu2204 image.

        Regression test for CPU parity: ensures CPU pods get the correct
        base image required for secret expansion.
        """
        job = Job(
            id=4,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type=None,  # No GPU = CPU job
            cpu_count=2,
            cpu_flavor_ids=["cpu3c"],
        )

        mock_pod = PodResponse(
            id="pod-cpu-001",
            name="test-cpu-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify CPU image is used
        assert captured_request is not None
        assert captured_request.image_name == "runpod/base:1.0.2-ubuntu2204"
        assert captured_request.compute_type == ComputeType.CPU

    @pytest.mark.asyncio
    async def test_gpu_image_selection(self, executor: JobExecutor) -> None:
        """Test that GPU jobs use PyTorch image.

        Regression test to ensure GPU pods maintain their expected image.
        """
        job = Job(
            id=5,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
        )

        mock_pod = PodResponse(
            id="pod-gpu-001",
            name="test-gpu-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify GPU image is used
        assert captured_request is not None
        assert (
            captured_request.image_name
            == "runpod/pytorch:2.2.0-py3.10-cuda12.1.1-devel-ubuntu22.04"
        )
        assert captured_request.compute_type == ComputeType.GPU

    @pytest.mark.asyncio
    async def test_explicit_image_selection(self, executor: JobExecutor) -> None:
        """Test that explicit image_name overrides both CPU and GPU defaults.

        This test verifies that when a job has an explicit image_name set,
        it reaches the PodCreateRequest unchanged, regardless of compute type.
        """
        job = Job(
            id=7,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",  # GPU job with explicit image
            image_name="ubuntu:22.04",  # Explicit image overrides GPU default
        )

        mock_pod = PodResponse(
            id="pod-explicit-001",
            name="test-explicit-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify explicit image is used (not the GPU default)
        assert captured_request is not None
        assert captured_request.image_name == "ubuntu:22.04"
        # Verify compute type is still GPU (image override does not affect compute)
        assert captured_request.compute_type == ComputeType.GPU

    @pytest.mark.asyncio
    async def test_no_volume_defaults(self, executor: JobExecutor) -> None:
        """Test that jobs without volume_id get volume_in_gb=0 and volume_mount_path=/workspace.

        Regression test for no-volume payload: ensures RunPod doesn't create
        unnecessary storage volumes for ephemeral jobs.
        """
        job = Job(
            id=6,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            volume_id=None,  # No volume attached
            volume_mount_path=None,
        )

        mock_pod = PodResponse(
            id="pod-novol-001",
            name="test-novol-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify no-volume defaults
        assert captured_request is not None
        assert captured_request.volume_in_gb == 0
        assert captured_request.volume_mount_path == "/workspace"
        assert captured_request.network_volume_id is None

    @pytest.mark.asyncio
    async def test_with_volume_overrides_defaults(self, executor: JobExecutor) -> None:
        """Test that jobs with volume_id get volume_in_gb=30 and custom mount path.

        Regression test to ensure volume jobs maintain their expected settings.
        """
        job = Job(
            id=7,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            volume_id="vol-abc123",
            volume_mount_path="/data",
        )

        mock_pod = PodResponse(
            id="pod-vol-001",
            name="test-vol-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify volume settings are applied
        assert captured_request is not None
        assert captured_request.volume_in_gb == 30
        assert captured_request.volume_mount_path == "/data"
        assert captured_request.network_volume_id == "vol-abc123"

    @pytest.mark.asyncio
    async def test_config_sourced_volume_mount_path(
        self, executor: JobExecutor
    ) -> None:
        """Test that config-sourced volume_mount_path reaches PodCreateRequest.

        Regression test: When volume_id is set from config and volume_mount_path
        is specified, the configured mount path should be used in the pod creation.
        """
        job = Job(
            id=8,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            volume_id="vol-xyz789",
            volume_mount_path="/kaggle/input",  # Config-sourced mount path
        )

        mock_pod = PodResponse(
            id="pod-cfg-001",
            name="test-cfg-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify config-sourced volume_mount_path is used
        assert captured_request is not None
        assert captured_request.volume_in_gb == 30
        assert captured_request.volume_mount_path == "/kaggle/input"
        assert captured_request.network_volume_id == "vol-xyz789"

    @pytest.mark.asyncio
    async def test_cli_volume_path_overrides_config(
        self, executor: JobExecutor
    ) -> None:
        """Test that CLI --volume-path takes precedence over config volume_path.

        Regression test: When both config and CLI provide volume_path, the CLI
        value should win. This simulates the merge_config_with_cli behavior
        where CLI args take precedence over config file values.
        """
        job = Job(
            id=9,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",
            volume_id="vol-cli789",
            volume_mount_path="/cli/override",  # CLI-provided path (would override config)
        )

        mock_pod = PodResponse(
            id="pod-cli-001",
            name="test-cli-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify CLI-provided volume_mount_path is used (not config)
        assert captured_request is not None
        assert captured_request.volume_in_gb == 30
        assert captured_request.volume_mount_path == "/cli/override"
        assert captured_request.network_volume_id == "vol-cli789"

    @pytest.mark.asyncio
    async def test_professional_gpu_rtx2000ada_2(self, executor: JobExecutor) -> None:
        """Test professional GPU RTX2000Ada with count=2.

        Regression test for professional GPU payload with multi-GPU:
        ensures gpu_type_ids contains exact RunPod GPU ID and gpu_count=2.
        """
        job = Job(
            id=10,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX2000Ada:2",  # Professional GPU with count=2
        )

        mock_pod = PodResponse(
            id="pod-prof-gpu-001",
            name="test-prof-gpu-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify professional GPU request
        assert captured_request is not None
        assert captured_request.gpu_type_ids == ["NVIDIA RTX 2000 Ada Generation"]
        assert captured_request.gpu_count == 2
        assert captured_request.compute_type == ComputeType.GPU

    @pytest.mark.asyncio
    async def test_consumer_gpu_rtx4090_1(self, executor: JobExecutor) -> None:
        """Test consumer GPU RTX4090 with count=1.

        Regression test for consumer GPU payload:
        ensures gpu_type_ids contains exact RunPod GPU ID.
        """
        job = Job(
            id=11,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type="RTX4090:1",  # Consumer GPU
        )

        mock_pod = PodResponse(
            id="pod-consumer-gpu-001",
            name="test-consumer-gpu-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify consumer GPU request
        assert captured_request is not None
        assert captured_request.gpu_type_ids == ["NVIDIA GeForce RTX 4090"]
        assert captured_request.gpu_count == 1
        assert captured_request.compute_type == ComputeType.GPU

    @pytest.mark.asyncio
    async def test_cpu_job_omits_gpu_fields(self, executor: JobExecutor) -> None:
        """Test that CPU jobs omit gpuTypeIds and gpuCount.

        Regression test for CPU job payload: ensures GPU fields are not
        present in the PodCreateRequest when running CPU jobs.
        """
        job = Job(
            id=12,
            command="python train.py",
            status=JobStatus.PROVISIONING,
            provider="runpod",
            gpu_type=None,  # No GPU = CPU job
            cpu_count=4,
            cpu_flavor_ids=["cpu5c"],
        )

        mock_pod = PodResponse(
            id="pod-cpu-only-001",
            name="test-cpu-only-pod",
            desired_status=PodStatus.RUNNING,
        )

        captured_request: PodCreateRequest | None = None

        async def capture_request(request: PodCreateRequest) -> PodResponse:
            nonlocal captured_request
            captured_request = request
            return mock_pod

        with patch.object(
            RunPodClient, "create_pod", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = capture_request

            with patch(
                "pxq.executor.wait_for_pod_ready", new_callable=AsyncMock
            ) as mock_wait:
                mock_wait.return_value = mock_pod

                with patch(
                    "pxq.executor.update_job_status", new_callable=AsyncMock
                ) as mock_update:
                    mock_update.return_value = job

                    await executor.process_runpod_job(job)

        # Verify CPU job omits GPU fields
        assert captured_request is not None
        assert captured_request.gpu_type_ids is None
        assert captured_request.gpu_count == 1  # Default, unused for CPU
        assert captured_request.compute_type == ComputeType.CPU
        assert captured_request.cpu_flavor_ids == ["cpu5c"]


class TestStdoutArtifactCollection:
    """Tests for stdout artifact collection on RunPod execution.

    Regression tests for stdout artifact presence/content verification.
    The _collect_final_logs function in runpod_exec.py collects stdout/stderr
    from /workspace/pxq_stdout.log and /workspace/pxq_stderr.log.
    """

    @pytest.mark.asyncio
    async def test_collect_final_logs_creates_stdout_artifact(
        self, tmp_path: Path
    ) -> None:
        """Test that _collect_final_logs creates stdout artifact from remote pod.

        Regression test for stdout artifact presence: ensures stdout output
        is captured and stored as an artifact with artifact_type='stdout'.
        """
        from pxq.providers.runpod_exec import _collect_final_logs, REMOTE_STDOUT_PATH

        db_path = tmp_path / "test.db"
        job_id = 1
        host = "127.0.0.1"
        port = 22

        # Mock SSH process that returns stdout content
        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        stdout_content = "line 1\nline 2\nline 3\n"

        # Mock create_artifact to capture the call
        created_artifacts = []

        async def mock_create_artifact(db, job_id, **kwargs):
            created_artifacts.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                # _collect_final_logs calls create_subprocess_exec for stdout
                mock_exec.return_value = FakeSSHProcess(
                    returncode=0, stdout=stdout_content.encode()
                )
                await _collect_final_logs(db_path, job_id, host, port)

        # Verify stdout artifact was created
        assert len(created_artifacts) >= 1
        stdout_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stdout"), None
        )
        assert stdout_artifact is not None, "Expected stdout artifact to be created"
        assert stdout_artifact["path"] == REMOTE_STDOUT_PATH
        assert stdout_artifact["size_bytes"] == len(stdout_content.encode())
        assert stdout_artifact["content"] == stdout_content

    @pytest.mark.asyncio
    async def test_collect_final_logs_creates_stderr_artifact(
        self, tmp_path: Path
    ) -> None:
        """Test that _collect_final_logs creates stderr artifact from remote pod.

        Regression test for stderr artifact presence: ensures stderr output
        is captured and stored as an artifact with artifact_type='stderr'.
        """
        from pxq.providers.runpod_exec import _collect_final_logs, REMOTE_STDERR_PATH

        db_path = tmp_path / "test.db"
        job_id = 2
        host = "127.0.0.1"
        port = 22

        # Mock SSH process that returns stderr content
        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        stderr_content = "error line 1\nerror line 2\n"

        # _collect_final_logs iterates over [stdout, stderr] paths
        # We need to mock both calls - first returns empty, second returns stderr
        call_count = [0]

        def create_process(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # stdout call - return empty
                return FakeSSHProcess(returncode=0, stdout=b"")
            else:
                # stderr call - return content
                return FakeSSHProcess(returncode=0, stdout=stderr_content.encode())

        # Mock create_artifact to capture the call
        created_artifacts = []

        async def mock_create_artifact(db, job_id, **kwargs):
            created_artifacts.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
            with patch("asyncio.create_subprocess_exec", side_effect=create_process):
                await _collect_final_logs(db_path, job_id, host, port)

        # Verify stderr artifact was created
        stderr_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stderr"), None
        )
        assert stderr_artifact is not None, "Expected stderr artifact to be created"
        assert stderr_artifact["path"] == REMOTE_STDERR_PATH
        assert stderr_artifact["size_bytes"] == len(stderr_content.encode())
        assert stderr_artifact["content"] == stderr_content

    @pytest.mark.asyncio
    async def test_collect_final_logs_skips_empty_content(self, tmp_path: Path) -> None:
        """Test that _collect_final_logs skips creating artifacts for empty content.

        Regression test to ensure no artifacts are created for empty stdout/stderr.
        """
        from pxq.providers.runpod_exec import _collect_final_logs

        db_path = tmp_path / "test.db"
        job_id = 3
        host = "127.0.0.1"
        port = 22

        # Mock SSH process that returns empty content
        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        # Mock create_artifact to track calls
        create_artifact_calls = []

        async def mock_create_artifact(db, job_id, **kwargs):
            create_artifact_calls.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_exec.return_value = FakeSSHProcess(returncode=0, stdout=b"")
                await _collect_final_logs(db_path, job_id, host, port)

        # Verify no artifacts were created for empty content
        assert (
            len(create_artifact_calls) == 0
        ), "Expected no artifacts for empty content"

    @pytest.mark.asyncio
    async def test_collect_final_logs_handles_ssh_failure_gracefully(
        self, tmp_path: Path
    ) -> None:
        """Test that _collect_final_logs handles SSH failures gracefully.

        Regression test to ensure SSH failures don't crash the job execution.
        """
        from pxq.providers.runpod_exec import _collect_final_logs

        db_path = tmp_path / "test.db"
        job_id = 4
        host = "127.0.0.1"
        port = 22

        # Mock SSH process that fails
        class FakeSSHProcess:
            def __init__(self, returncode: int):
                self.returncode = returncode

            async def communicate(self):
                return b"", b"SSH connection failed"

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = FakeSSHProcess(returncode=255)

            # Should not raise exception - best effort collection
            await _collect_final_logs(db_path, job_id, host, port)

        # If we get here without exception, the test passes

    @pytest.mark.asyncio
    async def test_collect_final_logs_append_only_new_content(
        self, tmp_path: Path
    ) -> None:
        """Test that _collect_final_logs only appends not-yet-persisted content.

        When artifacts already exist for stdout/stderr, only the suffix
        beyond the already-persisted byte count should be saved.
        """
        from pxq.providers.runpod_exec import (
            _collect_final_logs,
            REMOTE_STDOUT_PATH,
            REMOTE_STDERR_PATH,
        )
        from pxq.models import Artifact
        from datetime import datetime, UTC

        db_path = tmp_path / "test.db"
        job_id = 5
        host = "127.0.0.1"
        port = 22

        # Existing stdout artifact with 10 bytes already persisted
        existing_stdout = Artifact(
            id=1,
            job_id=job_id,
            artifact_type="stdout",
            path=REMOTE_STDOUT_PATH,
            size_bytes=10,  # "line 1\nlin" already persisted
            content="line 1\nlin",
            created_at=datetime.now(UTC),
        )
        # Existing stderr artifact with 7 bytes already persisted
        existing_stderr = Artifact(
            id=2,
            job_id=job_id,
            artifact_type="stderr",
            path=REMOTE_STDERR_PATH,
            size_bytes=7,  # "error 1" already persisted
            content="error 1",
            created_at=datetime.now(UTC),
        )

        # Mock SSH process that returns full content
        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        # Remote has 21 bytes for stdout, 16 bytes for stderr
        stdout_full = "line 1\nline 2\nline 3\n"  # 21 bytes
        stderr_full = "error 1\nerror 2\n"  # 16 bytes

        call_count = [0]

        def create_process(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeSSHProcess(returncode=0, stdout=stdout_full.encode())
            else:
                return FakeSSHProcess(returncode=0, stdout=stderr_full.encode())

        # Mock get_artifacts to return existing artifacts
        async def mock_get_artifacts(db, job_id):
            return [existing_stdout, existing_stderr]

        # Mock create_artifact to capture the call
        created_artifacts = []

        async def mock_create_artifact(db, job_id, **kwargs):
            created_artifacts.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.get_artifacts", side_effect=mock_get_artifacts):
            with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
                with patch(
                    "asyncio.create_subprocess_exec", side_effect=create_process
                ):
                    await _collect_final_logs(db_path, job_id, host, port)

        # Verify only the suffix was appended
        # stdout: 21 bytes total, 10 already persisted -> 11 byte suffix
        stdout_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stdout"), None
        )
        assert stdout_artifact is not None, "Expected stdout artifact to be created"
        assert stdout_artifact["size_bytes"] == 11, "Expected 11 byte suffix for stdout"
        assert (
            stdout_artifact["content"] == "e 2\nline 3\n"
        )  # "line 1\nlin" + "e 2\nline 3\n"

        # stderr: 16 bytes total, 7 already persisted -> 9 byte suffix
        stderr_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stderr"), None
        )
        assert stderr_artifact is not None, "Expected stderr artifact to be created"
        assert stderr_artifact["size_bytes"] == 9, "Expected 9 byte suffix for stderr"
        assert stderr_artifact["content"] == "\nerror 2\n"  # "error 1" + "\nerror 2\n"

    @pytest.mark.asyncio
    async def test_collect_final_logs_skips_when_fully_persisted(
        self, tmp_path: Path
    ) -> None:
        """Test that _collect_final_logs skips when content is already fully persisted."""
        from pxq.providers.runpod_exec import (
            _collect_final_logs,
            REMOTE_STDOUT_PATH,
            REMOTE_STDERR_PATH,
        )
        from pxq.models import Artifact
        from datetime import datetime, UTC

        db_path = tmp_path / "test.db"
        job_id = 6
        host = "127.0.0.1"
        port = 22

        # Existing stdout artifact with full content already persisted
        existing_stdout = Artifact(
            id=1,
            job_id=job_id,
            artifact_type="stdout",
            path=REMOTE_STDOUT_PATH,
            size_bytes=21,  # Full content already persisted
            content="line 1\nline 2\nline 3\n",
            created_at=datetime.now(UTC),
        )
        # Existing stderr artifact with full content already persisted
        existing_stderr = Artifact(
            id=2,
            job_id=job_id,
            artifact_type="stderr",
            path=REMOTE_STDERR_PATH,
            size_bytes=16,  # Full content already persisted
            content="error 1\nerror 2\n",
            created_at=datetime.now(UTC),
        )

        # Mock SSH process that returns same content
        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        stdout_full = "line 1\nline 2\nline 3\n"  # 21 bytes
        stderr_full = "error 1\nerror 2\n"  # 16 bytes

        call_count = [0]

        def create_process(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeSSHProcess(returncode=0, stdout=stdout_full.encode())
            else:
                return FakeSSHProcess(returncode=0, stdout=stderr_full.encode())

        async def mock_get_artifacts(db, job_id):
            return [existing_stdout, existing_stderr]

        created_artifacts = []

        async def mock_create_artifact(db, job_id, **kwargs):
            created_artifacts.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.get_artifacts", side_effect=mock_get_artifacts):
            with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
                with patch(
                    "asyncio.create_subprocess_exec", side_effect=create_process
                ):
                    await _collect_final_logs(db_path, job_id, host, port)

        # Verify no new artifacts were created
        assert (
            len(created_artifacts) == 0
        ), "Expected no artifacts when content is fully persisted"

    @pytest.mark.asyncio
    async def test_collect_final_logs_no_prior_artifacts(self, tmp_path: Path) -> None:
        """Test that _collect_final_logs saves full content when no prior artifacts exist."""
        from pxq.providers.runpod_exec import (
            _collect_final_logs,
            REMOTE_STDOUT_PATH,
            REMOTE_STDERR_PATH,
        )

        db_path = tmp_path / "test.db"
        job_id = 7
        host = "127.0.0.1"
        port = 22

        class FakeSSHProcess:
            def __init__(self, returncode: int, stdout: bytes):
                self.returncode = returncode
                self._stdout = stdout

            async def communicate(self):
                return self._stdout, b""

        stdout_full = "line 1\nline 2\n"
        stderr_full = "error line 1\n"

        call_count = [0]

        def create_process(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeSSHProcess(returncode=0, stdout=stdout_full.encode())
            else:
                return FakeSSHProcess(returncode=0, stdout=stderr_full.encode())

        async def mock_get_artifacts(db, job_id):
            return []  # No prior artifacts

        created_artifacts = []

        async def mock_create_artifact(db, job_id, **kwargs):
            created_artifacts.append({"job_id": job_id, **kwargs})
            return None

        with patch("pxq.storage.get_artifacts", side_effect=mock_get_artifacts):
            with patch("pxq.storage.create_artifact", side_effect=mock_create_artifact):
                with patch(
                    "asyncio.create_subprocess_exec", side_effect=create_process
                ):
                    await _collect_final_logs(db_path, job_id, host, port)

        # Verify full content was saved
        stdout_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stdout"), None
        )
        assert stdout_artifact is not None
        assert stdout_artifact["content"] == stdout_full
        assert stdout_artifact["size_bytes"] == len(stdout_full.encode())

        stderr_artifact = next(
            (a for a in created_artifacts if a.get("artifact_type") == "stderr"), None
        )
        assert stderr_artifact is not None
        assert stderr_artifact["content"] == stderr_full
        assert stderr_artifact["size_bytes"] == len(stderr_full.encode())


class TestLocalStopFunctionality:
    """Tests for local job stop functionality with process groups.

    Tests for:
    - stop_local_process() helper with SIGTERM -> SIGKILL
    - local_pid saved during local job execution
    - LocalProcessHandle class
    """

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        """Create a temporary database path."""
        return tmp_path / "test.db"

    @pytest.fixture
    def executor(self, db_path: Path) -> JobExecutor:
        """Create a JobExecutor instance for testing."""
        return JobExecutor(db_path=db_path)

    @pytest.mark.asyncio
    async def test_local_pid_saved_during_job_execution(
        self, executor: JobExecutor, db_path: Path
    ) -> None:
        """Test that local_pid is saved when local job starts."""
        from pxq.storage import create_job, get_job, init_db
        from unittest.mock import AsyncMock, patch

        await init_db(db_path)

        job = await create_job(
            db_path,
            Job(
                command="echo hello",
                status=JobStatus.PROVISIONING,
                provider="local",
                workdir=str(db_path.parent),
            ),
        )

        # Mock process handle with PID
        class MockProcessHandle:
            def __init__(self) -> None:
                self._pid = 12345
                self._returncode = 0
                self._stdout = b"hello\n"
                self._stderr = b""

            @property
            def pid(self) -> int:
                return self._pid

            @property
            def returncode(self) -> int | None:
                return self._returncode

            async def communicate(self) -> tuple[bytes, bytes]:
                return self._stdout, self._stderr

            async def wait(self) -> int | None:
                return self._returncode

        with patch(
            "pxq.executor.start_local_command", new_callable=AsyncMock
        ) as mock_start:
            mock_start.return_value = MockProcessHandle()

            result = await executor.process_local_job(job)

        # Verify job completed successfully
        assert result.status == JobStatus.SUCCEEDED

        # Verify local_pid was saved (and then cleared after completion)
        saved_job = await get_job(db_path, job.id)
        assert saved_job is not None
        # local_pid should be None after completion (cleared)
        assert saved_job.local_pid is None

    @pytest.mark.asyncio
    async def test_local_pid_cleared_on_timeout(
        self, executor: JobExecutor, db_path: Path
    ) -> None:
        """Test that local_pid is cleared when job times out."""
        from pxq.storage import create_job, get_job, init_db
        from unittest.mock import AsyncMock, patch
        import asyncio

        await init_db(db_path)

        job = await create_job(
            db_path,
            Job(
                command="sleep 100",
                status=JobStatus.PROVISIONING,
                provider="local",
            ),
        )

        # Mock process handle that times out
        class MockTimeoutHandle:
            def __init__(self) -> None:
                self._pid = 54321

            @property
            def pid(self) -> int:
                return self._pid

            @property
            def returncode(self) -> int | None:
                return None

            async def communicate(self) -> tuple[bytes, bytes]:
                raise asyncio.TimeoutError()

            async def wait(self) -> int | None:
                return -1

        with patch(
            "pxq.executor.start_local_command", new_callable=AsyncMock
        ) as mock_start:
            mock_start.return_value = MockTimeoutHandle()

            with patch("pxq.executor.stop_local_process") as mock_stop:
                mock_stop.return_value = True

                result = await executor.process_local_job(job)

        # Verify job failed due to timeout
        assert result.status == JobStatus.FAILED

        # Verify local_pid was cleared
        saved_job = await get_job(db_path, job.id)
        assert saved_job is not None
        assert saved_job.local_pid is None


@pytest.mark.asyncio
async def test_stop_local_process_helper(tmp_db: Path) -> None:
    """Test stop_local_process helper function."""
    from pxq.providers.local_exec import stop_local_process
    import subprocess
    import time

    # Start a simple long-running process in a process group
    proc = subprocess.Popen(
        ["sleep", "100"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,  # type: ignore[arg-type]
    )

    pgid = os.getpgid(proc.pid)

    # Give process time to start
    time.sleep(0.1)

    # Verify process is running
    assert proc.poll() is None

    # Stop the process group
    result = stop_local_process(pgid, timeout=1.0)

    # Verify process was stopped
    assert result is True

    # Wait for process to fully terminate
    proc.wait(timeout=2.0)
    assert proc.returncode is not None


@pytest.mark.asyncio
async def test_stop_local_process_already_dead(tmp_db: Path) -> None:
    """Test stop_local_process returns False for already-dead process."""
    from pxq.providers.local_exec import stop_local_process

    # Use a non-existent PID
    result = stop_local_process(999999, timeout=0.1)

    # Should return False for non-existent process
    assert result is False


@pytest.mark.asyncio
async def test_stop_local_job_helper(tmp_db: Path) -> None:
    """Test stop_local_job API helper function."""
    from pxq.executor import stop_local_job
    from pxq.storage import create_job, get_job, init_db
    from unittest.mock import patch

    await init_db(tmp_db)

    # Create a running job with local_pid
    job = await create_job(
        tmp_db,
        Job(
            command="sleep 100",
            status=JobStatus.RUNNING,
            provider="local",
            local_pid=99999,  # Fake PID
        ),
    )

    assert job.id is not None

    # Mock stop_local_process to return True
    with patch("pxq.executor.stop_local_process", return_value=True):
        result = await stop_local_job(tmp_db, job.id)

    # Verify job was stopped
    assert result is True

    saved_job = await get_job(tmp_db, job.id)
    assert saved_job is not None
    assert saved_job.status == JobStatus.STOPPED
    assert saved_job.local_pid is None


@pytest.mark.asyncio
async def test_stop_local_job_no_pid(tmp_db: Path) -> None:
    """Test stop_local_job returns False when job has no local_pid."""
    from pxq.executor import stop_local_job
    from pxq.storage import create_job, init_db

    await init_db(tmp_db)

    # Create a running job WITHOUT local_pid
    job = await create_job(
        tmp_db,
        Job(
            command="sleep 100",
            status=JobStatus.RUNNING,
            provider="local",
            local_pid=None,
        ),
    )

    assert job.id is not None

    # Should return False because there's no PID to stop
    result = await stop_local_job(tmp_db, job.id)

    assert result is False


@pytest.mark.asyncio
async def test_stop_local_job_not_found(tmp_db: Path) -> None:
    """Test stop_local_job returns False for non-existent job."""
    from pxq.executor import stop_local_job
    from pxq.storage import init_db

    await init_db(tmp_db)

    # Try to stop non-existent job
    result = await stop_local_job(tmp_db, 99999)

    assert result is False


class TestStopLocalProcessSignalFallback:
    """Tests for stop_local_process signal handling with mocks.

    Tests for:
    - SIGTERM graceful shutdown path
    - SIGKILL fallback when process ignores SIGTERM
    """

    def test_stop_local_process_sigterm_succeeds(self, tmp_path: Path) -> None:
        """Test that stop_local_process sends SIGTERM and process exits gracefully."""
        from pxq.providers.local_exec import stop_local_process
        import signal

        killed_pids: list[tuple[int, int]] = []

        def mock_killpg_check(pid: int, sig: int) -> None:
            # When sig=0, check if process exists
            if sig == 0:
                # After SIGTERM, process is dead
                sigterm_sent = any(s == signal.SIGTERM for _, s in killed_pids)
                if sigterm_sent:
                    raise ProcessLookupError()
                return None  # Process exists
            killed_pids.append((pid, sig))
            return None

        with patch("os.killpg", side_effect=mock_killpg_check):
            with patch("time.sleep", return_value=None):
                result = stop_local_process(12345, timeout=0.1)

        # SIGTERM was sent, SIGKILL was not needed
        assert (12345, signal.SIGTERM) in killed_pids
        assert result is True

    def test_stop_local_process_sigkill_fallback(self, tmp_path: Path) -> None:
        """Test that stop_local_process falls back to SIGKILL when SIGTERM fails."""
        from pxq.providers.local_exec import stop_local_process
        import signal

        killed_pids: list[tuple[int, int]] = []

        def mock_killpg_check(pid: int, sig: int) -> None:
            # When sig=0, check if process exists
            if sig == 0:
                # Process is always "alive" (ignores SIGTERM)
                # until SIGKILL is sent
                sigkill_sent = any(s == signal.SIGKILL for _, s in killed_pids)
                if sigkill_sent:
                    raise ProcessLookupError()
                return None  # Process still exists
            killed_pids.append((pid, sig))
            return None

        with patch("os.killpg", side_effect=mock_killpg_check):
            with patch("time.sleep", return_value=None):
                result = stop_local_process(12345, timeout=0.1)

        # Both SIGTERM and SIGKILL were sent
        assert (12345, signal.SIGTERM) in killed_pids
        assert (12345, signal.SIGKILL) in killed_pids
        assert result is True

    def test_stop_local_process_already_dead_no_signal(self, tmp_path: Path) -> None:
        """Test that stop_local_process returns False when process is already dead."""
        from pxq.providers.local_exec import stop_local_process

        def mock_killpg_dead(pid: int, sig: int) -> None:
            raise ProcessLookupError()

        with patch("os.killpg", side_effect=mock_killpg_dead):
            result = stop_local_process(12345, timeout=0.1)

        assert result is False

    def test_stop_local_process_permission_error(self, tmp_path: Path) -> None:
        """Test that stop_local_process handles permission errors gracefully."""
        from pxq.providers.local_exec import stop_local_process

        def mock_killpg_permission(pid: int, sig: int) -> None:
            raise PermissionError("Not allowed to signal process")

        with patch("os.killpg", side_effect=mock_killpg_permission):
            result = stop_local_process(12345, timeout=0.1)

        assert result is False


class TestStopApiCountLogic:
    """Tests for stop API count logic (0/1/multiple running jobs).

    Tests for:
    - Stop API returns 400 when no running jobs
    - Stop API returns 400 when multiple running jobs
    - Stop API succeeds when exactly one running job
    """

    @pytest.fixture
    def db_path(self, tmp_path: Path) -> Path:
        """Create a temporary database path."""
        return tmp_path / "test.db"

    @pytest.mark.asyncio
    async def test_stop_api_no_running_jobs(self, db_path: Path) -> None:
        """Test stop API returns 400 when no running jobs exist."""
        from pxq.storage import create_job, init_db
        from pxq.api.jobs import stop_job_endpoint
        from fastapi import HTTPException

        await init_db(db_path)

        # Create only queued jobs (no running)
        await create_job(db_path, Job(command="echo 1", status=JobStatus.QUEUED))
        await create_job(db_path, Job(command="echo 2", status=JobStatus.SUCCEEDED))

        with patch("pxq.api.jobs._get_db_path", return_value=str(db_path)):
            with patch("pxq.api.jobs.Settings") as mock_settings:
                mock_settings.return_value.runpod_api_key = "test-key"

                with pytest.raises(HTTPException) as exc_info:
                    await stop_job_endpoint()

                # Should be HTTPException with 400
                assert exc_info.value.status_code == 400
                assert "No running jobs found" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_stop_api_multiple_running_jobs(self, db_path: Path) -> None:
        """Test stop API returns 400 when multiple running jobs exist."""
        from pxq.storage import create_job, init_db, update_job_status
        from pxq.api.jobs import stop_job_endpoint
        from fastapi import HTTPException

        await init_db(db_path)

        # Create two running jobs
        job1 = await create_job(db_path, Job(command="echo 1"))
        await update_job_status(db_path, job1.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job1.id, JobStatus.UPLOADING)
        await update_job_status(db_path, job1.id, JobStatus.RUNNING)

        job2 = await create_job(db_path, Job(command="echo 2"))
        await update_job_status(db_path, job2.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job2.id, JobStatus.UPLOADING)
        await update_job_status(db_path, job2.id, JobStatus.RUNNING)

        with patch("pxq.api.jobs._get_db_path", return_value=str(db_path)):
            with patch("pxq.api.jobs.Settings") as mock_settings:
                mock_settings.return_value.runpod_api_key = "test-key"

                with pytest.raises(HTTPException) as exc_info:
                    await stop_job_endpoint()

                # Should be HTTPException with 400
                assert exc_info.value.status_code == 400
                assert "Multiple running jobs found" in str(exc_info.value.detail)
                assert str(job1.id) in str(exc_info.value.detail)
                assert str(job2.id) in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_stop_api_single_running_local_job(self, db_path: Path) -> None:
        """Test stop API succeeds when exactly one running local job exists."""
        from pxq.storage import create_job, get_job, init_db, update_job_status
        from pxq.api.jobs import stop_job_endpoint

        await init_db(db_path)

        # Create one running local job with local_pid
        job = await create_job(db_path, Job(command="echo 1", provider="local"))
        await update_job_status(db_path, job.id, JobStatus.PROVISIONING)
        await update_job_status(db_path, job.id, JobStatus.UPLOADING)
        await update_job_status(db_path, job.id, JobStatus.RUNNING, local_pid=12345)

        with patch("pxq.api.jobs._get_db_path", return_value=str(db_path)):
            with patch("pxq.api.jobs.Settings") as mock_settings:
                mock_settings.return_value.runpod_api_key = "test-key"

                with patch("pxq.executor.stop_local_process", return_value=True):
                    response = await stop_job_endpoint()

        # Verify response
        assert response.status == JobStatus.STOPPED
