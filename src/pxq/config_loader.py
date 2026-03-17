"""Config file loader and path resolution for pxq CLI.

This module provides utilities for:
- Loading YAML configuration files
- Resolving relative paths to absolute paths
- Merging CLI arguments with config file values
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigFileError(Exception):
    """Raised when config file cannot be loaded."""


def load_config_file(path: Path | str) -> dict[str, Any]:
    """Load a YAML configuration file.

    Parameters
    ----------
    path : Path | str
        Path to the YAML config file.

    Returns
    -------
    dict[str, Any]
        Parsed configuration dictionary.

    Raises
    ------
    ConfigFileError
        If the file does not exist or contains invalid YAML.
    """
    config_path = Path(path)

    if not config_path.exists():
        raise ConfigFileError(f"Config file not found: {config_path}")

    if not config_path.is_file():
        raise ConfigFileError(f"Config path is not a file: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as f:
            content = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"Invalid YAML in config file: {exc}") from exc

    if content is None:
        return {}

    if not isinstance(content, dict):
        raise ConfigFileError(
            f"Config file must contain a YAML mapping, got {type(content).__name__}"
        )

    # Reject stale mount_path key
    if "mount_path" in content:
        raise ConfigFileError(
            "Invalid config key 'mount_path'. Use 'volume_path' instead."
        )

    # Reject simultaneous image_name and template_id
    if "image_name" in content and "template_id" in content:
        raise ConfigFileError(
            "Invalid config: 'image_name' and 'template_id' are mutually exclusive. "
            "Specify only one of them."
        )

    # Normalize gpu alias to gpu_type
    if "gpu" in content:
        if "gpu_type" in content:
            # Both keys present - check for conflict
            if content["gpu"] != content["gpu_type"]:
                raise ConfigFileError(
                    f"Invalid config: conflicting GPU specifications. "
                    f"'gpu: {content['gpu']}' and 'gpu_type: {content['gpu_type']}' differ. "
                    f"Use only 'gpu_type' (recommended) or 'gpu' (alias)."
                )

            # Same value - drop the redundant gpu key
            del content["gpu"]
        else:
            # Only gpu present - normalize to gpu_type
            content["gpu_type"] = content.pop("gpu")

    return content


def resolve_workdir(path: str | None) -> Path:
    """Resolve a working directory path to an absolute path.

    Parameters
    ----------
    path : str | None
        Path to resolve. If None, returns current working directory.

    Returns
    -------
    Path
        Absolute path to the working directory.
    """
    if path is None:
        return Path.cwd()

    workdir = Path(path)

    if workdir.is_absolute():
        return workdir

    return workdir.resolve()


def merge_config_with_cli(
    cli_args: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Merge CLI arguments with config file values.

    CLI arguments take precedence over config file values.
    Only keys present in cli_args are considered for merging.

    Parameters
    ----------
    cli_args : dict[str, Any]
        Arguments from CLI. None values indicate the argument was not provided.
    config : dict[str, Any]
        Configuration from file.

    Returns
    -------
    dict[str, Any]
        Merged configuration with CLI values taking precedence.
    """
    result: dict[str, Any] = {}

    for key, cli_value in cli_args.items():
        # CLI value takes precedence if it's not None
        if cli_value is not None:
            result[key] = cli_value
        elif key in config:
            # Fall back to config file value
            result[key] = config[key]

    return result
