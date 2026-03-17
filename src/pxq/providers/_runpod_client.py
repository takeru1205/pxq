"""RunPod API client with typed models for pod lifecycle operations.

This module provides a typed interface to the RunPod GraphQL API for managing
GPU/CPU pods including creation, status checking, and stopping.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

import httpx
from pydantic import BaseModel


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
        """Check if the status is a terminal state.

        Parameters
        ----------
        status : PodStatus
            The status to check.

        Returns
        -------
        bool
            True if the status is terminal (no further changes expected).
        """
        return status in {
            cls.STOPPED,
            cls.EXITED,
            cls.TERMINATED,
            cls.ERROR,
        }

    @classmethod
    def is_ready(cls, status: "PodStatus") -> bool:
        """Check if the pod is ready for use.

        Parameters
        ----------
        status : PodStatus
            The status to check.

        Returns
        -------
        bool
            True if the pod is ready for SSH/command execution.
        """
        return status == cls.RUNNING


class CloudType(str, Enum):
    """RunPod cloud type enumeration."""

    SECURE = "SECURE"
    COMMUNITY = "COMMUNITY"
    ALL = "ALL"


class ComputeType(str, Enum):
    """RunPod compute type enumeration."""

    GPU = "GPU"
    CPU = "CPU"


class PodMachine(BaseModel):
    """Machine information for a running pod.

    Attributes
    ----------
    id : Optional[str]
        Machine ID.
    public_ip : Optional[str]
        Public IP address for SSH access.
    hostname : Optional[str]
        Machine hostname.
    port : Optional[int]
        SSH port number.
    gpu_type : Optional[str]
        GPU type (e.g., "NVIDIA RTX 4090").
    gpu_count : Optional[int]
        Number of GPUs.
    cpu_count : Optional[int]
        Number of CPUs.
    ram_in_gb : Optional[int]
        RAM in gigabytes.
    disk_in_gb : Optional[int]
        Disk size in gigabytes.
    cuda_version : Optional[str]
        CUDA version.
    country : Optional[str]
        Country code where the machine is located.
    cloud_type : Optional[str]
        Cloud type (SECURE or COMMUNITY).
    """

    id: Optional[str] = None
    public_ip: Optional[str] = None
    hostname: Optional[str] = None
    port: Optional[int] = None
    gpu_type: Optional[str] = None
    gpu_count: Optional[int] = None
    cpu_count: Optional[int] = None
    ram_in_gb: Optional[int] = None
    disk_in_gb: Optional[int] = None
    cuda_version: Optional[str] = None
    country: Optional[str] = None
    cloud_type: Optional[str] = None


class PodCreateRequest(BaseModel):
    """Request model for creating a new RunPod pod.

    Attributes
    ----------
    name : str
        Pod name.
    image_name : str
        Docker image name (e.g., "runpod/pytorch:latest").
    gpu_type_id : Optional[str]
        GPU type ID (e.g., "NVIDIA RTX 4090"). Required for GPU pods.
    cloud_type : CloudType
        Cloud type (SECURE or COMMUNITY). Defaults to ALL.
    compute_type : Optional[ComputeType]
        Compute type (GPU or CPU). Defaults to GPU if gpu_type_id is set.
    container_disk_in_gb : Optional[int]
        Container disk size in gigabytes.
    volume_in_gb : Optional[int]
        Network volume size in gigabytes.
    volume_mount_path : Optional[str]
        Path to mount the network volume.
    ports : Optional[str]
        Ports to expose (e.g., "22/tcp,8080/http").
    env : Optional[dict[str, str]]
        Environment variables.
    docker_args : Optional[str]
        Additional Docker arguments.
    gpu_count : int
        Number of GPUs. Defaults to 1.
    min_memory_in_gb : Optional[int]
        Minimum RAM in gigabytes.
    network_volume_id : Optional[str]
    Network volume ID to attach.
    start_ssh : bool
    Whether to start SSH service. Defaults to True.
    data_center_id : Optional[str]
    RunPod data center ID (e.g., "EU-RO-1").
    """

    name: str
    image_name: str
    gpu_type_id: Optional[str] = None
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
    start_ssh: bool = True
    support_public_ip: bool = True
    data_center_id: Optional[str] = None


class PodResponse(BaseModel):
    """Response model for RunPod pod operations.

    Attributes
    ----------
    id : str
        Unique pod identifier.
    name : Optional[str]
        Pod name.
    status : PodStatus
        Current pod status.
    desired_status : Optional[str]
        Desired status (e.g., "RUNNING", "EXITED").
    image_name : Optional[str]
        Docker image name.
    machine : Optional[PodMachine]
        Machine information (when pod is running).
    runtime : Optional[dict[str, Any]]
        Runtime information including ports.
    ports : Optional[list[dict[str, Any]]]
        Exposed ports.
    volume_mounts : Optional[list[dict[str, Any]]]
        Volume mount information.
    cost_per_hr : Optional[float]
        Cost per hour in credits.
    created_at : Optional[str]
        Creation timestamp.
    """

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
        """Get SSH host address.

        Returns
        -------
        Optional[str]
            SSH host address if available.
        """
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
        """Get SSH port number.

        Returns
        -------
        int
            SSH port number (defaults to 22).
        """
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


class RunPodError(Exception):
    """Base exception for RunPod API errors.

    Attributes
    ----------
    message : str
        Error message.
    status_code : Optional[int]
        HTTP status code if applicable.
    error_type : Optional[str]
        Error type from RunPod API.
    """

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
    """Exception raised when rate limit is exceeded (HTTP 429)."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message, status_code=429, error_type="RATE_LIMIT")


class RunPodAPIError(RunPodError):
    """Exception raised for API errors (5xx responses)."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, status_code=status_code, error_type="API_ERROR")


class GraphQLResponse(BaseModel):
    """GraphQL response wrapper.

    Attributes
    ----------
    data : Optional[dict[str, Any]]
        Response data.
    errors : Optional[list[dict[str, Any]]]
        GraphQL errors.
    """

    data: Optional[dict[str, Any]] = None
    errors: Optional[list[dict[str, Any]]] = None


class RunPodClient:
    """RunPod GraphQL API client for pod lifecycle operations.

    This client provides typed methods for creating, querying, and stopping
    RunPod pods using the GraphQL API.

    Attributes
    ----------
    api_key : str
        RunPod API key.
    base_url : str
        GraphQL API base URL.

    Examples
    --------
    >>> client = RunPodClient(api_key="your-api-key")
    >>> request = PodCreateRequest(
    ...     name="my-pod",
    ...     image_name="runpod/pytorch:latest",
    ...     gpu_type_ids=["NVIDIA RTX 4090"],
    ... )
    >>> pod = await client.create_pod(request)
    >>> pod = await client.create_pod(request)
    >>> print(pod.id)
    """

    GRAPHQL_URL = "https://api.runpod.io/graphql"

    def __init__(self, api_key: str) -> None:
        """Initialize the RunPod client.

        Parameters
        ----------
        api_key : str
            RunPod API key.
        """
        self.api_key = api_key
        self.base_url = f"{self.GRAPHQL_URL}?api_key={api_key}"

    def _get_headers(self) -> dict[str, str]:
        """Get HTTP headers for API requests.

        Returns
        -------
        dict[str, str]
            HTTP headers.
        """
        return {
            "Content-Type": "application/json",
        }

    async def _execute_graphql(
        self,
        client: httpx.AsyncClient,
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query.

        Parameters
        ----------
        client : httpx.AsyncClient
            HTTP client to use.
        query : str
            GraphQL query string.
        variables : Optional[dict[str, Any]]
            Query variables.

        Returns
        -------
        dict[str, Any]
            Response data.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If API returns an error.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        response = await client.post(
            self.base_url,
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

    async def create_pod(self, request: PodCreateRequest) -> PodResponse:
        """Create a new RunPod pod.

        Uses the podFindAndDeployOnDemand mutation to create and deploy a pod.

        Parameters
        ----------
        request : PodCreateRequest
            Pod creation request.

        Returns
        -------
        PodResponse
            Created pod information.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If pod creation fails.
        """
        mutation = """
        mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
            podFindAndDeployOnDemand(input: $input) {
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

        # Build input variables
        input_vars: dict[str, Any] = {
            "name": request.name,
            "imageName": request.image_name,
            "gpuCount": request.gpu_count,
            "startSsh": request.start_ssh,
            "supportPublicIp": request.support_public_ip,
        }

        if request.gpu_type_id:
            input_vars["gpuTypeId"] = request.gpu_type_id

        if request.cloud_type != CloudType.ALL:
            input_vars["cloudType"] = request.cloud_type.value

        if request.compute_type:
            input_vars["computeType"] = request.compute_type.value

        if request.container_disk_in_gb:
            input_vars["containerDiskInGb"] = request.container_disk_in_gb

        if request.volume_in_gb:
            input_vars["volumeInGb"] = request.volume_in_gb

        if request.volume_mount_path:
            input_vars["volumeMountPath"] = request.volume_mount_path

        if request.ports:
            input_vars["ports"] = request.ports

        if request.env:
            input_vars["env"] = request.env

        if request.docker_args:
            input_vars["dockerArgs"] = request.docker_args

        if request.min_memory_in_gb:
            input_vars["minMemoryInGb"] = request.min_memory_in_gb

        if request.network_volume_id:
            input_vars["networkVolumeId"] = request.network_volume_id

        if request.data_center_id:
            input_vars["dataCenterId"] = request.data_center_id

        async with httpx.AsyncClient() as client:
            data = await self._execute_graphql(client, mutation, {"input": input_vars})

        pod_data = data.get("podFindAndDeployOnDemand", {})
        return self._parse_pod_response(pod_data)

    async def get_pod(self, pod_id: str) -> PodResponse:
        """Get pod information by ID.

        Parameters
        ----------
        pod_id : str
            Pod ID to query.

        Returns
        -------
        PodResponse
            Pod information.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If pod query fails.
        """
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
        """Stop a running pod.

        Parameters
        ----------
        pod_id : str
            Pod ID to stop.

        Returns
        -------
        PodResponse
            Updated pod information.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If pod stop fails.
        """
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
        """Terminate a pod.

        Parameters
        ----------
        pod_id : str
            Pod ID to terminate.

        Returns
        -------
        PodResponse
            Updated pod information.

        Raises
        ------
        RunPodRateLimitError
            If rate limit is exceeded.
        RunPodAPIError
            If pod terminate fails.
        """
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
        """Parse pod response data into PodResponse model.

        Parameters
        ----------
        data : dict[str, Any]
            Raw pod data from API.

        Returns
        -------
        PodResponse
            Parsed pod response.
        """
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

        return PodResponse(
            id=data.get("id", ""),
            name=data.get("name"),
            status=status,
            desired_status=data.get("desiredStatus"),
            image_name=data.get("imageName"),
            machine=machine,
            runtime=data.get("runtime"),
            ports=data.get("ports"),
            volume_mounts=volume_mounts,
            cost_per_hr=data.get("costPerHr"),
            created_at=data.get("createdAt"),
        )
