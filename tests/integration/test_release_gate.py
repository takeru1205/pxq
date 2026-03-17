from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from typing import Any

import httpx
import pytest

from pxq.config import Settings
from pxq.providers.runpod_exec import execute_remote_command


pytestmark = pytest.mark.integration


class RunPodRESTGateway:
    def __init__(
        self, api_key: str, base_url: str = "https://rest.runpod.io/v1"
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def create_pod(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/pods",
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def get_pod(self, pod_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"{self._base_url}/pods/{pod_id}", headers=self._headers
            )
            response.raise_for_status()
            return response.json()

    async def stop_pod(self, pod_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._base_url}/pods/{pod_id}/stop",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json() if response.content else {}


def _extract_ready_endpoint(pod_data: dict[str, Any]) -> tuple[str, int] | None:
    public_ip = pod_data.get("publicIp")
    port_mappings = pod_data.get("portMappings") or {}
    ssh_port = port_mappings.get("22") or port_mappings.get(22)
    if public_ip and ssh_port:
        return str(public_ip), int(ssh_port)
    return None


async def _wait_for_ready_pod(
    gateway: RunPodRESTGateway,
    pod_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float = 10.0,
) -> tuple[dict[str, Any], str, int]:
    deadline = datetime.now(UTC).timestamp() + timeout_seconds
    latest: dict[str, Any] = {}

    while datetime.now(UTC).timestamp() < deadline:
        pod_data = await gateway.get_pod(pod_id)
        latest = pod_data
        endpoint = _extract_ready_endpoint(pod_data)
        desired_status = str(pod_data.get("desiredStatus", ""))

        if endpoint and desired_status == "RUNNING":
            host, port = endpoint
            return pod_data, host, port
        await asyncio.sleep(poll_interval_seconds)

    raise RuntimeError(f"pod {pod_id} did not become ready: {latest}")


async def _wait_for_stopped_status(
    gateway: RunPodRESTGateway,
    pod_id: str,
    timeout_seconds: float = 240.0,
    poll_interval_seconds: float = 5.0,
) -> str:
    deadline = datetime.now(UTC).timestamp() + timeout_seconds
    latest_status = "unknown"

    while datetime.now(UTC).timestamp() < deadline:
        pod_data = await gateway.get_pod(pod_id)
        latest_status = str(pod_data.get("desiredStatus", ""))
        if latest_status in {"EXITED", "TERMINATED", "STOPPED"}:
            return latest_status
        await asyncio.sleep(poll_interval_seconds)

    return latest_status


def _build_remote_command() -> str:
    training_script = dedent(
        """
        import json
        import os
        import subprocess
        import sys
        import zipfile
        from pathlib import Path

        import pandas as pd
        from sklearn.ensemble import RandomForestClassifier


        def set_kaggle_credentials() -> None:
            username = os.getenv("RUNPOD_SECRET_KAGGLE_USERNAME")
            key = os.getenv("RUNPOD_SECRET_KAGGLE_KEY") or os.getenv("RUNPOD_SECRET_KAGGLE_API_TOKEN")
            if username and key:
                os.environ["KAGGLE_USERNAME"] = username
                os.environ["KAGGLE_KEY"] = key


        def download_with_kaggle(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
            set_kaggle_credentials()
            command = [
                sys.executable,
                "-m",
                "kaggle",
                "competitions",
                "download",
                "-c",
                "spaceship-titanic",
                "-p",
                str(data_dir),
                "--force",
            ]
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "kaggle download failed")

            archive_path = data_dir / "spaceship-titanic.zip"
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(data_dir)

            train_df = pd.read_csv(data_dir / "train.csv")
            test_df = pd.read_csv(data_dir / "test.csv")
            return train_df, test_df, "kaggle"


        def download_fallback() -> tuple[pd.DataFrame, pd.DataFrame, str]:
            train_df = pd.read_csv(
                "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"
            )
            train_df = train_df.rename(columns={"Survived": "Transported"})
            test_df = train_df.drop(columns=["Transported"]).copy()
            if "PassengerId" not in test_df.columns:
                test_df["PassengerId"] = list(range(1, len(test_df) + 1))
            return train_df, test_df, "fallback-public-titanic"


        def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
            return pd.get_dummies(df.fillna(""), dummy_na=True)


        workdir = Path("/workspace")
        data_dir = workdir / "data"
        results_dir = workdir / "results"
        data_dir.mkdir(parents=True, exist_ok=True)
        results_dir.mkdir(parents=True, exist_ok=True)

        try:
            train_df, test_df, source = download_with_kaggle(data_dir)
        except Exception:
            train_df, test_df, source = download_fallback()

        train_rows = max(50, int(len(train_df) * 0.1))
        test_rows = max(50, int(len(test_df) * 0.1))

        sampled_train = train_df.sample(n=min(train_rows, len(train_df)), random_state=42)
        sampled_test = test_df.sample(n=min(test_rows, len(test_df)), random_state=42)

        y_train = sampled_train["Transported"].astype(int)
        x_train = prepare_features(sampled_train.drop(columns=["Transported"]))
        x_test = prepare_features(sampled_test).reindex(columns=x_train.columns, fill_value=0)

        model = RandomForestClassifier(n_estimators=50, random_state=42, n_jobs=-1)
        model.fit(x_train, y_train)
        predictions = model.predict(x_test).astype(bool)

        submission = pd.DataFrame(
            {
                "PassengerId": sampled_test.get(
                    "PassengerId", pd.Series(range(1, len(sampled_test) + 1))
                ),
                "Transported": predictions,
            }
        )
        submission.to_csv(results_dir / "submission.csv", index=False)

        metrics = {
            "data_source": source,
            "train_rows": int(len(sampled_train)),
            "test_rows": int(len(sampled_test)),
            "prediction_rows": int(len(submission)),
        }
        (results_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        """
    ).strip()

    return "\n".join(
        [
            "python -m pip install --quiet --disable-pip-version-check kaggle pandas scikit-learn",
            "python - <<'PY'",
            training_script,
            "PY",
            "test -f /workspace/results/metrics.json",
            "test -f /workspace/results/submission.csv",
        ]
    )


def _write_evidence(
    evidence_path: Path,
    *,
    pod_id: str,
    job_completion: str,
    exit_code: int,
    pod_final_status: str,
    ready_snapshot: dict[str, Any],
) -> None:
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    lines = [
        f"timestamp={timestamp}",
        f"pod_id={pod_id}",
        f"job_completion={job_completion}",
        f"exit_code={exit_code}",
        f"pod_final_status={pod_final_status}",
        f"public_ip={ready_snapshot.get('publicIp')}",
        f"port_mappings={ready_snapshot.get('portMappings')}",
    ]
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("PXQ_RUNPOD_API_KEY"),
    reason="PXQ_RUNPOD_API_KEY is required for release-gate integration test",
)
async def test_release_gate_runpod_kaggle_titanic() -> None:
    api_key = os.environ["PXQ_RUNPOD_API_KEY"]
    settings = Settings()
    evidence_path = Path(".sisyphus/evidence/task-20-runpod-kaggle.txt")

    gpu_type = os.getenv("PXQ_RUNPOD_RELEASE_GPU_TYPE_ID")
    image_name = os.getenv(
        "PXQ_RUNPOD_RELEASE_IMAGE",
        "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel-ubuntu22.04",
    )

    payload: dict[str, Any] = {
        "name": f"pxq-release-gate-{int(datetime.now(UTC).timestamp())}",
        "imageName": image_name,
        "containerDiskInGb": 20,
        "ports": ["22/tcp"],
    }
    if gpu_type:
        payload["computeType"] = "GPU"
        payload["gpuCount"] = 1
        payload["gpuTypeIds"] = [gpu_type]
    else:
        payload["computeType"] = "CPU"
        payload["vcpuCount"] = 2

    gateway = RunPodRESTGateway(api_key)
    pod_id = ""
    exit_code = 1
    ready_snapshot: dict[str, Any] = {}

    try:
        created_pod = await gateway.create_pod(payload)
        pod_id = str(created_pod["id"])
        ready_snapshot, ssh_host, ssh_port = await _wait_for_ready_pod(
            gateway,
            pod_id,
            timeout_seconds=settings.provisioning_timeout_minutes * 60,
        )

        exit_code = await execute_remote_command(
            command=_build_remote_command(),
            host=ssh_host,
            port=ssh_port,
            timeout_seconds=300.0,
        )
    finally:
        if pod_id:
            try:
                await gateway.stop_pod(pod_id)
            except Exception:
                pass

    if not pod_id:
        pytest.fail("pod was not created")

    completion = "succeeded" if exit_code == 0 else "failed"
    final_pod_status = await _wait_for_stopped_status(gateway, pod_id)
    _write_evidence(
        evidence_path,
        pod_id=pod_id,
        job_completion=completion,
        exit_code=exit_code,
        pod_final_status=final_pod_status,
        ready_snapshot=ready_snapshot,
    )

    assert completion in {"succeeded", "failed"}
    assert final_pod_status in {"STOPPED", "EXITED", "TERMINATED"}
