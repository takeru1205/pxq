from __future__ import annotations

from enum import Enum
from typing import Any, Optional

import httpx
from pydantic import BaseModel

from pxq.providers.runpod_ssh import SSHConnectionInfo


class PodStatus(str, Enum):
    """RunPod pod status enumeration.

    Status values from RunPod API:
    - CREATED: Pod has been created but not yet deployed
    - LAUNCHING: Pod is being launched
    - RUNNING: Pod is running and ready
    - RUNNING_UNHEALTHY: Pod is running but unhealthy
    - STOPPED: Pod has been stopped
    - STOPPING: Pod is being stopped
    - EXITED: Pod has exited
    - TERMINATED: Pod has been terminated
    - ERROR: Pod encountered an error
    """

    CREATED = "CREATED"
    LAUNCHING = "LAUNCHING"
    RUNNING = "RUNNING"
    RUNNING_UNHEALTHY = "RUNNING_UNHEALTHY"
    STOPPED = "STOPPED"
    STOPPING = "STOPPING"
    EXITED = "EXITED"
    TERMINATED = "TERMINATED"
    ERROR = "ERROR"

    @classmethod
    def is_terminal(cls, status: "PodStatus") -> bool:
        return status in {
            cls.STOPPED,
            cls.EXITED,
            cls.TERMINATED,
            cls.ERROR,
        }

    @classmethod
    def is_ready(cls, status: "PodStatus") -> bool:
        return status == cls.RUNNING


class CloudType(str, Enum):
    SECURE = "SECURE"
    COMMUNITY = "COMMUNITY"
    ALL = "ALL"


class ComputeType(str, Enum):
    GPU = "GPU"
    CPU = "CPU"


class PodMachine(BaseModel):
    id: Optional[str] = None
    public_ip: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None
    pod_host_id: Optional[str] = None
    gpu_type: Optional[str] = None
    gpu_count: Optional[int] = None
    cpu_count: Optional[int] = None
    ram_in_gb: Optional[int] = None
    disk_in_gb: Optional[int] = None
    cuda_version: Optional[str] = None
    country: Optional[str] = None
    cloud_type: Optional[str] = None


class PodCreateRequest(BaseModel):
    name: str
    image_name: str
    gpu_type_ids: Optional[list[str]] = None
    cloud_type: CloudType = CloudType.ALL
    compute_type: Optional[ComputeType] = None
    container_disk_in_gb: Optional[int] = None
    volume_in_gb: Optional[int] = None
    volume_mount_path: Optional[str] = None
    ports: Optional[str] = None
    env: Optional[dict[str, str]] = None
    docker_args: Optional[str] = None
    gpu_count: int = 1
    min_memory_in_gb: Optional[int] = None
    network_volume_id: Optional[str] = None
    cpu_flavor_ids: Optional[list[str]] = None
    vcpu_count: Optional[int] = None
    template_id: Optional[str] = None
    start_ssh: bool = True
    support_public_ip: bool = True
    data_center_ids: Optional[list[str]] = None
    ssh_pubkey: Optional[str] = None


class PodResponse(BaseModel):
    id: str
    name: Optional[str] = None
    status: PodStatus = PodStatus.CREATED
    desired_status: Optional[str] = None
    image_name: Optional[str] = None
    machine: Optional[PodMachine] = None
    runtime: Optional[dict[str, Any]] = None
    ports: Optional[list[dict[str, Any]]] = None
    volume_mounts: Optional[list[dict[str, Any]]] = None
    cost_per_hr: Optional[float] = None
    created_at: Optional[str] = None

    @property
    def has_public_ssh(self) -> bool:
        runtime_ports = (
            self.runtime.get("ports") if isinstance(self.runtime, dict) else None
        )
        if not isinstance(runtime_ports, list):
            return False
        for port_info in runtime_ports:
            if not isinstance(port_info, dict):
                continue
            if (
                port_info.get("isIpPublic")
                and port_info.get("privatePort") == 22
                and isinstance(port_info.get("publicPort"), int)
            ):
                return True
        return False

    @property
    def ssh_host(self) -> Optional[str]:
        runtime_ports = (
            self.runtime.get("ports") if isinstance(self.runtime, dict) else None
        )
        if isinstance(runtime_ports, list):
            for port_info in runtime_ports:
                if not isinstance(port_info, dict):
                    continue
                if port_info.get("privatePort") == 22 and port_info.get("isIpPublic"):
                    ip = port_info.get("ip")
                    if isinstance(ip, str) and ip:
                        return ip
            for port_info in runtime_ports:
                if not isinstance(port_info, dict):
                    continue
                if port_info.get("isIpPublic"):
                    ip = port_info.get("ip")
                    if isinstance(ip, str) and ip:
                        return ip

        if self.machine and self.machine.public_ip:
            return self.machine.public_ip
        return None

    @property
    def ssh_port(self) -> int:
        runtime_ports = (
            self.runtime.get("ports") if isinstance(self.runtime, dict) else None
        )
        if isinstance(runtime_ports, list):
            for port_info in runtime_ports:
                if not isinstance(port_info, dict):
                    continue
                if port_info.get("privatePort") == 22 and port_info.get("isIpPublic"):
                    public_port = port_info.get("publicPort")
                    if isinstance(public_port, int) and public_port > 0:
                        return public_port
            for port_info in runtime_ports:
                if not isinstance(port_info, dict):
                    continue
                if port_info.get("isIpPublic"):
                    public_port = port_info.get("publicPort")
                    if isinstance(public_port, int) and public_port > 0:
                        return public_port

        if self.machine and self.machine.port:
            return self.machine.port
        return 22

    def _direct_tcp_s(self, host: str, port: int) -> SSHConnectionInfo:
        return SSHConnectionInfo(
            method="direct_tcp",
            host=host,
            port=port,
            username="root",
            supports_file_transfer=True,
        )

    @property
    def ssh_connection_info(self) -> Optional[SSHConnectionInfo]:
        """Get SSH connection information for the pod."""
        if self.machine and self.machine.pod_host_id:
            return SSHConnectionInfo(
                method="proxy",
                host="ssh.runpod.io",
                port=None,
                username=f"{self.id}-{self.machine.pod_host_id}",
                supports_file_transfer=False,
            )

        # Look for public SSH port in runtime ports
        runtime_ports = (
            self.runtime.get("ports") if isinstance(self.runtime, dict) else None
        )
        if isinstance(runtime_ports, list):
            for port_info in runtime_ports:
                if (
                    isinstance(port_info, dict)
                    and port_info.get("privatePort") == 22
                    and port_info.get("isIpPublic")
                ):
                    public_port = port_info.get("publicPort")
                    ip = port_info.get("ip")
                    if (
                        isinstance(public_port, int)
                        and public_port > 0
                        and isinstance(ip, str)
                        and ip
                    ):
                        return self._direct_tcp_s(ip, public_port)

        # If no specific SSH port found, try any public IP and port 22
        if self.machine and self.machine.public_ip:
            return self._direct_tcp_s(self.machine.public_ip, 22)

        return None


class RunPodError(Exception):
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_type: Optional[str] = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        super().__init__(message)


class RunPodRateLimitError(RunPodError):
    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, status_code=429, error_type="RATE_LIMIT")


class RunPodAPIError(RunPodError):
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, status_code=status_code, error_type="API_ERROR")


class GraphQLResponse(BaseModel):
    data: Optional[dict[str, Any]] = None
    errors: Optional[list[dict[str, Any]]] = None


class RunPodClient:
    GRAPHQL_URL = "https://api.runpod.io/graphql"
    REST_URL = "https://rest.runpod.io"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.graphql_url = f"{self.GRAPHQL_URL}?api_key={api_key}"

    def _get_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
        }

    def _get_rest_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _execute_graphql(
        self,
        client: httpx.AsyncClient,
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await client.post(
            self.graphql_url,
            json=payload,
            headers=self._get_headers(),
        )

        if response.status_code == 429:
            raise RunPodRateLimitError()

        if response.status_code >= 500:
            raise RunPodAPIError(
                f"API error: {response.status_code}",
                status_code=response.status_code,
            )

        if response.status_code >= 400:
            error_detail = response.text
            raise RunPodAPIError(
                f"Request failed: {error_detail}",
                status_code=response.status_code,
            )

        graphql_response = GraphQLResponse(**response.json())

        if graphql_response.errors:
            error_msg = graphql_response.errors[0].get("message", "Unknown error")
            raise RunPodAPIError(f"GraphQL error: {error_msg}")

        if not graphql_response.data:
            raise RunPodAPIError("No data in response")

        return graphql_response.data

    async def delete_pod(self, pod_id: str) -> None:
        """Delete a pod via RunPod REST API.

        Parameters
        ----------
        pod_id : str
            Pod ID to delete.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If pod deletion fails.
        """
        url = f"{self.REST_URL}/v1/pods/{pod_id}"

        async with httpx.AsyncClient() as client:
            response = await client.delete(
                url,
                headers=self._get_rest_headers(),
            )

        if response.status_code == 429:
            raise RunPodRateLimitError()

        # 200 OK or 204 No Content means success
        if response.status_code in (200, 204):
            return

        # 404 means pod is already deleted or doesn't exist - treat as success
        if response.status_code == 404:
            return

        if response.status_code >= 500:
            raise RunPodAPIError(
                f"Delete pod API error: {response.status_code}",
                status_code=response.status_code,
            )

        # For other status codes, check if it's an error response
        try:
            error_data = response.json()
            error_msg = error_data.get(
                "error", response.text.strip() or "unknown delete failure"
            )
        except Exception:
            error_msg = response.text.strip() or "unknown delete failure"

        raise RunPodAPIError(
            f"Delete pod request failed: {error_msg}",
            status_code=response.status_code,
        )

    async def create_pod(self, request: PodCreateRequest) -> PodResponse:
        """Create a pod using RunPod REST API.

        REST endpoint: POST https://rest.runpod.io/v1/pods
        Auth: Bearer token via Authorization header
        """
        # Build REST API payload - map snake_case to camelCase
        # Minimal payload first, then add optional fields
        payload: dict[str, Any] = {
            "name": request.name,
            "ports": request.ports.split(",") if request.ports else ["22/tcp"],
        }

        # Image name (optional - uses RunPod default if not specified)
        if request.image_name:
            payload["imageName"] = request.image_name

        # Compute type specific fields
        if request.compute_type == ComputeType.CPU:
            # CPU pod: set computeType=CPU, cpuFlavorIds
            # Omit gpuTypeIds entirely
            # Omit vcpuCount (use RunPod default of 2)
            payload["computeType"] = "CPU"
            if request.cpu_flavor_ids:
                payload["cpuFlavorIds"] = request.cpu_flavor_ids
        elif request.compute_type == ComputeType.GPU:
            # GPU pod: set computeType=GPU, gpuTypeIds, gpuCount
            payload["computeType"] = "GPU"
            if request.gpu_type_ids:
                payload["gpuTypeIds"] = request.gpu_type_ids
            payload["gpuCount"] = request.gpu_count

        # Cloud type
        if request.cloud_type != CloudType.ALL:
            payload["cloudType"] = request.cloud_type.value

        # Data center IDs
        if request.data_center_ids:
            payload["dataCenterIds"] = request.data_center_ids

        # Network volume (preferred over local volume)
        if request.network_volume_id:
            payload["networkVolumeId"] = request.network_volume_id
            if request.volume_mount_path:
                payload["volumeMountPath"] = request.volume_mount_path

        # Local volume settings (only if no network volume)
        elif request.volume_in_gb:
            payload["volumeInGb"] = request.volume_in_gb
            if request.volume_mount_path:
                payload["volumeMountPath"] = request.volume_mount_path

        # Container disk (optional, has default of 50GB)
        if request.container_disk_in_gb:
            payload["containerDiskInGb"] = request.container_disk_in_gb

        # Memory requirement (optional)
        if request.min_memory_in_gb:
            payload["minMemoryInGb"] = request.min_memory_in_gb

        # Template ID (env is defined in template)
        if request.template_id:
            payload["templateId"] = request.template_id

        # Docker arguments (optional)
        if request.docker_args:
            payload["dockerArgs"] = request.docker_args

        # Environment variables (passed verbatim to RunPod for server-side secret expansion)
        if request.env:
            payload["env"] = request.env

        if request.ssh_pubkey:
            payload["sshPubkey"] = request.ssh_pubkey

        import sys
        import json

        print("=" * 80, file=sys.stderr)
        print("=== POD CREATE REQUEST ===", file=sys.stderr)
        print(f"URL: {self.REST_URL}/v1/pods", file=sys.stderr)
        print("Method: POST", file=sys.stderr)
        print(
            f"Headers: {json.dumps(self._get_rest_headers(), indent=2)}",
            file=sys.stderr,
        )
        print("Body (payload):", file=sys.stderr)
        print(json.dumps(payload, indent=2), file=sys.stderr)
        print("=" * 80, file=sys.stderr)

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.REST_URL}/v1/pods",
                headers=self._get_rest_headers(),
                json=payload,
            )
            print("=" * 80, file=sys.stderr)
            print("=== POD CREATE RESPONSE ===", file=sys.stderr)
            print(f"Status: {response.status_code}", file=sys.stderr)
            print(f"Headers: {dict(response.headers)}", file=sys.stderr)
            print("Body:", file=sys.stderr)
            print(response.text[:2000], file=sys.stderr)
            print("=" * 80, file=sys.stderr)

            if response.status_code == 429:
                raise RunPodRateLimitError()

            if response.status_code >= 500:
                raise RunPodAPIError(
                    f"API error: {response.status_code}",
                    status_code=response.status_code,
                )

            if response.status_code >= 400:
                error_detail = response.text
                raise RunPodAPIError(
                    f"Request failed: {error_detail}",
                    status_code=response.status_code,
                )

            pod_data = response.json()

        return self._parse_pod_response(pod_data)

    async def get_pod(self, pod_id: str) -> PodResponse:
        query = """
        query GetPod($podId: String!) {
            pod(input: {podId: $podId}) {
                id
                name
                desiredStatus
                imageName
                runtime {
                    ports {
                        ip
                        isIpPublic
                        privatePort
                        publicPort
                        type
                    }
                }
                machine {
                    id
                    runpodIp
                }
                volumeMountPath
                costPerHr
                createdAt
            }
        }
        """

        async with httpx.AsyncClient() as client:
            data = await self._execute_graphql(client, query, {"podId": pod_id})

        pod_data = data.get("pod", {})
        if not pod_data:
            raise RunPodAPIError(f"Pod not found: {pod_id}")

        return self._parse_pod_response(pod_data)

    async def stop_pod(self, pod_id: str) -> PodResponse:
        mutation = """
        mutation StopPod($podId: String!) {
            podStop(input: {podId: $podId}) {
                id
                name
                desiredStatus
                imageName
                machine {
                    id
                    runpodIp
                }
                volumeMountPath
                costPerHr
                createdAt
            }
        }
        """

        async with httpx.AsyncClient() as client:
            data = await self._execute_graphql(client, mutation, {"podId": pod_id})

        pod_data = data.get("podStop", {})
        return self._parse_pod_response(pod_data)

    async def terminate_pod(self, pod_id: str) -> PodResponse:
        mutation = """
        mutation TerminatePod($podId: String!) {
            podTerminate(input: {podId: $podId})
        }
        """

        async with httpx.AsyncClient() as client:
            data = await self._execute_graphql(client, mutation, {"podId": pod_id})

        _ = data.get("podTerminate")

        try:
            return await self.get_pod(pod_id)
        except RunPodAPIError as exc:
            if "Pod not found" in str(exc):
                return PodResponse(
                    id=pod_id,
                    status=PodStatus.TERMINATED,
                    desired_status=PodStatus.TERMINATED.value,
                )
            raise

    def _parse_pod_response(self, data: dict[str, Any]) -> PodResponse:
        machine_data = data.get("machine")
        machine = None
        if machine_data:
            public_ip = machine_data.get("runpodIp") or machine_data.get("publicIp")
            if isinstance(public_ip, str) and "/" in public_ip:
                public_ip = public_ip.split("/", 1)[0]
            machine = PodMachine(
                id=machine_data.get("id"),
                public_ip=public_ip,
                hostname=machine_data.get("hostname"),
                port=machine_data.get("port"),
                gpu_type=machine_data.get("gpuType"),
                gpu_count=machine_data.get("gpuCount"),
                cpu_count=machine_data.get("cpuCount"),
                ram_in_gb=machine_data.get("ramInGb"),
                disk_in_gb=machine_data.get("diskInGb"),
                cuda_version=machine_data.get("cudaVersion"),
                country=machine_data.get("country"),
                cloud_type=machine_data.get("cloudType"),
            )

        status_str = data.get("status") or data.get("desiredStatus") or "CREATED"
        try:
            status = PodStatus(status_str)
        except ValueError:
            status = PodStatus.CREATED

        volume_mounts = data.get("volumeMounts")
        volume_mount_path = data.get("volumeMountPath")
        if volume_mounts is None and volume_mount_path:
            volume_mounts = [{"mountPath": volume_mount_path}]

        # Handle REST API ports format (list of strings) vs model (list of dicts)
        ports_data = data.get("ports")
        if (
            isinstance(ports_data, list)
            and ports_data
            and isinstance(ports_data[0], str)
        ):
            # REST API returns ["22/tcp", "8080/http"] - convert to dict format
            ports_data = [
                {
                    "publicPort": p.split("/")[0],
                    "type": p.split("/")[1] if "/" in p else "tcp",
                }
                for p in ports_data
            ]

        return PodResponse(
            id=data.get("id", ""),
            name=data.get("name"),
            status=status,
            desired_status=data.get("desiredStatus"),
            image_name=data.get("imageName"),
            machine=machine,
            runtime=data.get("runtime"),
            ports=ports_data,
            volume_mounts=volume_mounts,
            cost_per_hr=data.get("costPerHr"),
            created_at=data.get("createdAt"),
        )
