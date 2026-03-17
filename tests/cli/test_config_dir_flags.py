"""Tests for config file loading and path resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pxq.config_loader import (
    ConfigFileError,
    load_config_file,
    merge_config_with_cli,
    resolve_workdir,
)


class TestLoadConfigFile:
    """Tests for load_config_file function."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        """Test loading a valid YAML config file."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
provider: runpod
gpu_type: RTX4090:1
managed: true
volume_id: vol-123
"""
        )

        result = load_config_file(config_file)

        assert result == {
            "provider": "runpod",
            "gpu_type": "RTX4090:1",
            "managed": True,
            "volume_id": "vol-123",
        }

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        """Test loading an empty YAML file returns empty dict."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        result = load_config_file(config_file)

        assert result == {}

    def test_load_yaml_with_comments(self, tmp_path: Path) -> None:
        """Test loading YAML with comments."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            """
# This is a comment
provider: local  # inline comment
managed: false
"""
        )

        result = load_config_file(config_file)

        assert result == {
            "provider": "local",
            "managed": False,
        }

    def test_missing_file_raises_error(self, tmp_path: Path) -> None:
        """Test that missing config file raises ConfigFileError."""
        missing_file = tmp_path / "nonexistent.yaml"

        with pytest.raises(ConfigFileError, match="Config file not found"):
            load_config_file(missing_file)

    def test_directory_raises_error(self, tmp_path: Path) -> None:
        """Test that passing a directory raises ConfigFileError."""
        with pytest.raises(ConfigFileError, match="Config path is not a file"):
            load_config_file(tmp_path)

    def test_invalid_yaml_raises_error(self, tmp_path: Path) -> None:
        """Test that invalid YAML raises ConfigFileError."""
        config_file = tmp_path / "invalid.yaml"
        # Use truly invalid YAML - unclosed bracket
        config_file.write_text("provider: [unclosed\n")

        with pytest.raises(ConfigFileError, match="Invalid YAML"):
            load_config_file(config_file)

    def test_non_mapping_yaml_raises_error(self, tmp_path: Path) -> None:
        """Test that non-mapping YAML raises ConfigFileError."""
        config_file = tmp_path / "list.yaml"
        config_file.write_text("- item1\n- item2\n")

        with pytest.raises(ConfigFileError, match="must contain a YAML mapping"):
            load_config_file(config_file)

    def test_load_with_string_path(self, tmp_path: Path) -> None:
        """Test loading config with string path instead of Path."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("provider: local\n")

        result = load_config_file(str(config_file))

        assert result == {"provider": "local"}


class TestResolveWorkdir:
    """Tests for resolve_workdir function."""

    def test_resolve_none_returns_cwd(self) -> None:
        """Test that None returns current working directory."""
        result = resolve_workdir(None)

        assert result == Path.cwd()
        assert result.is_absolute()

    def test_resolve_absolute_path_unchanged(self, tmp_path: Path) -> None:
        """Test that absolute paths are returned unchanged."""
        result = resolve_workdir(str(tmp_path))

        assert result == tmp_path
        assert result.is_absolute()

    def test_resolve_relative_path(self, tmp_path: Path, monkeypatch: Any) -> None:
        """Test that relative paths are resolved to absolute."""
        # Change to tmp_path as cwd
        monkeypatch.chdir(tmp_path)

        result = resolve_workdir("subdir")

        assert result == tmp_path / "subdir"
        assert result.is_absolute()

    def test_resolve_dot_returns_cwd(self, monkeypatch: Any) -> None:
        """Test that '.' returns current working directory."""
        expected_cwd = Path.cwd()
        result = resolve_workdir(".")

        assert result == expected_cwd
        assert result.is_absolute()


class TestMergeConfigWithCli:
    """Tests for merge_config_with_cli function."""

    def test_cli_overrides_config(self) -> None:
        """Test that CLI values take precedence over config values."""
        cli_args = {
            "provider": "runpod",
            "gpu_type": None,
            "managed": True,
        }
        config = {
            "provider": "local",
            "gpu_type": "RTX4090:1",
            "managed": False,
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",  # CLI value
            "gpu_type": "RTX4090:1",  # Config value (CLI was None)
            "managed": True,  # CLI value
        }

    def test_empty_cli_returns_empty(self) -> None:
        """Test that empty CLI args returns empty dict."""
        result = merge_config_with_cli({}, {"provider": "runpod"})

        assert result == {}

    def test_empty_config_uses_cli_values(self) -> None:
        """Test that empty config uses CLI values."""
        cli_args = {"provider": "local", "managed": False}

        result = merge_config_with_cli(cli_args, {})

        assert result == {"provider": "local", "managed": False}

    def test_both_empty_returns_empty(self) -> None:
        """Test that both empty returns empty dict."""
        result = merge_config_with_cli({}, {})

        assert result == {}

    def test_cli_none_with_missing_config_key(self) -> None:
        """Test that CLI None with missing config key is not included."""
        cli_args = {"provider": "runpod", "gpu_type": None}
        config = {"provider": "local"}

        result = merge_config_with_cli(cli_args, config)

        assert result == {"provider": "runpod"}
        assert "gpu_type" not in result

    def test_complex_nested_values(self) -> None:
        """Test merging with complex nested values."""
        cli_args = {
            "provider": "runpod",
            "env_vars": None,
        }
        config = {
            "provider": "local",
            "env_vars": {"API_KEY": "secret", "DEBUG": "true"},
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "env_vars": {"API_KEY": "secret", "DEBUG": "true"},
        }

    def test_env_passthrough_from_config(self) -> None:
        """Test that config file env values survive merge when CLI env is None.

        This ensures RunPod secret placeholders like {{ RUNPOD_SECRET_* }}
        can be defined in config files without being overwritten by CLI.
        """
        cli_args = {
            "provider": "runpod",
            "env": None,  # CLI doesn't specify env
        }
        config = {
            "provider": "local",
            "env": {
                "API_KEY": "{{ RUNPOD_SECRET_api_key }}",
                "DATABASE_URL": "{{ RUNPOD_SECRET_database_url }}",
            },
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",  # CLI overrides
            "env": {  # Config value preserved (CLI was None)
                "API_KEY": "{{ RUNPOD_SECRET_api_key }}",
                "DATABASE_URL": "{{ RUNPOD_SECRET_database_url }}",
            },
        }

    def test_secure_cloud_config_parity_cli_none(self) -> None:
        """Test that secure_cloud from config is used when CLI is None.

        Regression test: CLI boolean defaults used to overwrite config values.
        When CLI secure_cloud is None (not specified), config value should be used.
        """
        cli_args = {
            "provider": "runpod",
            "secure_cloud": None,  # CLI not specified
        }
        config = {
            "provider": "local",
            "secure_cloud": True,  # Config specifies secure cloud
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",  # CLI overrides
            "secure_cloud": True,  # Config value preserved (CLI was None)
        }

    def test_secure_cloud_cli_explicit_false_overrides_config(self) -> None:
        """Test that CLI explicit False overrides config True.

        This verifies CLI precedence when user explicitly sets --no-secure-cloud.
        """
        cli_args = {
            "provider": "runpod",
            "secure_cloud": False,  # CLI explicitly False
        }
        config = {
            "provider": "local",
            "secure_cloud": True,  # Config has True
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "secure_cloud": False,  # CLI False overrides config True
        }

    def test_managed_config_parity_cli_none(self) -> None:
        """Test that managed from config is used when CLI is None.

        Regression test: CLI boolean defaults used to overwrite config values.
        When CLI managed is None (not specified), config value should be used.
        """
        cli_args = {
            "provider": "runpod",
            "managed": None,  # CLI not specified
        }
        config = {
            "provider": "local",
            "managed": True,  # Config specifies managed mode
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",  # CLI overrides
            "managed": True,  # Config value preserved (CLI was None)
        }

    def test_managed_cli_explicit_false_overrides_config(self) -> None:
        """Test that CLI explicit False overrides config True.

        This verifies CLI precedence when user explicitly sets --no-managed.
        """
        cli_args = {
            "provider": "runpod",
            "managed": False,  # CLI explicitly False
        }
        config = {
            "provider": "local",
            "managed": True,  # Config has True
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "managed": False,  # CLI False overrides config True
        }

    def test_both_boolean_flags_from_config(self) -> None:
        """Test that both secure_cloud and managed from config are preserved.

        Regression test for the specific failure scenario where config file had:
        - secure_cloud: true
        - managed: true

        But both were ignored because CLI booleans defaulted to False.
        """
        cli_args = {
            "provider": "runpod",
            "gpu_type": None,
            "secure_cloud": None,  # CLI not specified
            "managed": None,  # CLI not specified
        }
        config = {
            "provider": "runpod",
            "gpu_type": "RTX4090:1",
            "secure_cloud": True,
            "managed": True,
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "gpu_type": "RTX4090:1",  # Config value (CLI was None)
            "secure_cloud": True,  # Config value preserved
            "managed": True,  # Config value preserved
        }

    def test_volume_path_config_merge(self) -> None:
        """Test that volume_path from config survives merge when CLI is None.

        Regression test: volume_path key should be preserved from config file
        when CLI doesn't specify --volume-path.
        """
        cli_args = {
            "provider": "runpod",
            "volume": "vol-123",
            "volume_path": None,  # CLI not specified
        }
        config = {
            "provider": "runpod",
            "volume": "vol-456",
            "volume_path": "/kaggle/input",  # Config specifies volume_path
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "volume": "vol-123",  # CLI overrides
            "volume_path": "/kaggle/input",  # Config value preserved (CLI was None)
        }

    def test_mount_path_config_rejected(self, tmp_path: Path) -> None:
        """Test that mount_path (stale key) is rejected as invalid config.

        Regression test: mount_path was the old, incorrect key name.
        This test expects validation to reject mount_path once the fix lands.
        """
        # Load config with stale mount_path key
        config_file = tmp_path / "config-mount-path.yaml"
        config_file.write_text(
            """
provider: runpod
gpu_type: RTX4090:1
mount_path: /kaggle/input
"""
        )

        with pytest.raises(ConfigFileError) as exc_info:
            load_config_file(config_file)

        # Verify error message mentions mount_path -> volume_path
        assert "mount_path" in str(exc_info.value)
        assert "volume_path" in str(exc_info.value)

    def test_image_name_survives_config_merge(self) -> None:
        """Test that image_name from config survives merge when CLI is None.

        This test codifies the contract that image_name can be specified in
        YAML config and will be used when --image is not provided on CLI.
        """
        cli_args = {
            "provider": "runpod",
            "image_name": None,  # CLI not specified
            "template_id": None,
        }
        config = {
            "provider": "runpod",
            "image_name": "ubuntu:22.04",  # Config specifies image
        }

        result = merge_config_with_cli(cli_args, config)

        assert result == {
            "provider": "runpod",
            "image_name": "ubuntu:22.04",  # Config value preserved (CLI was None)
        }

    def test_image_name_and_template_id_config_conflict(self, tmp_path: Path) -> None:
        """Test that image_name and template_id together in config raises error.

        This test codifies the contract that image selection and template_id
        are mutually exclusive even when both come from config file.
        """
        config_file = tmp_path / "config-conflict.yaml"
        config_file.write_text(
            """
provider: runpod
image_name: ubuntu:22.04
template_id: tpl-123
"""
        )

        with pytest.raises(ConfigFileError) as exc_info:
            load_config_file(config_file)

        # Verify error message mentions both fields
        error_msg = str(exc_info.value)
        assert "image_name" in error_msg or "image" in error_msg
        assert "template_id" in error_msg or "template" in error_msg

    def test_gpu_alias_normalized_to_gpu_type(self, tmp_path: Path) -> None:
        """Test that 'gpu' alias is normalized to 'gpu_type'.

        The 'gpu' key is a backward-compatible alias for 'gpu_type'.
        When only 'gpu' is present, it should be renamed to 'gpu_type'.
        """
        config_file = tmp_path / "config-gpu-alias.yaml"
        config_file.write_text(
            """
provider: runpod
gpu: RTX4090:1
"""
        )

        result = load_config_file(config_file)

        # gpu should be normalized to gpu_type
        assert "gpu" not in result
        assert result.get("gpu_type") == "RTX4090:1"

    def test_gpu_alias_conflict_rejected(self, tmp_path: Path) -> None:
        """Test that conflicting 'gpu' and 'gpu_type' values are rejected.

        When both keys are present with different values, the config
        is ambiguous and should fail fast with a clear error message.
        """
        config_file = tmp_path / "config-gpu-conflict.yaml"
        config_file.write_text(
            """
provider: runpod
gpu: RTX4090:1
gpu_type: RTX3090:1
"""
        )

        with pytest.raises(ConfigFileError) as exc_info:
            load_config_file(config_file)

        # Verify error message mentions the conflict
        error_msg = str(exc_info.value)
        assert "gpu" in error_msg
        assert "gpu_type" in error_msg
        assert "conflict" in error_msg.lower()

    def test_gpu_alias_same_value_deduplicated(self, tmp_path: Path) -> None:
        """Test that redundant 'gpu' key is dropped when values match.

        When both 'gpu' and 'gpu_type' are present with the same value,
        the redundant 'gpu' key should be silently dropped.
        """
        config_file = tmp_path / "config-gpu-duplicate.yaml"
        config_file.write_text(
            """
provider: runpod
gpu: RTX4090:1
gpu_type: RTX4090:1
"""
        )

        result = load_config_file(config_file)

        # gpu should be dropped, only gpu_type remains
        assert "gpu" not in result
        assert result.get("gpu_type") == "RTX4090:1"
