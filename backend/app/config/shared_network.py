import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.errors import ConfigurationError

_REQUIRED_KEYS = frozenset({"network_id", "protocol_version"})


@dataclass(frozen=True)
class SharedNetworkConfig:
    network_id: str
    protocol_version: int


def load_shared_network_config(path: Path) -> SharedNetworkConfig:
    if not path.is_file():
        raise ConfigurationError(f"The shared network configuration file was not found at '{path}'.")

    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigurationError(f"The shared network configuration at '{path}' could not be read.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"The shared network configuration at '{path}' is not valid JSON.") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("The shared network configuration must be a JSON object.")

    unsupported = sorted(set(raw) - _REQUIRED_KEYS)
    if unsupported:
        raise ConfigurationError(
            "The shared network configuration contains settings that are not part of the shared "
            f"configuration: {', '.join(unsupported)}. Node-specific settings belong in the private node configuration."
        )

    missing = sorted(_REQUIRED_KEYS - set(raw))
    if missing:
        raise ConfigurationError(f"The shared network configuration is missing: {', '.join(missing)}.")

    network_id = raw["network_id"]
    if not isinstance(network_id, str) or not network_id.strip():
        raise ConfigurationError("The shared network setting 'network_id' must be a non-empty text value.")

    protocol_version = raw["protocol_version"]
    if isinstance(protocol_version, bool) or not isinstance(protocol_version, int) or protocol_version < 1:
        raise ConfigurationError("The shared network setting 'protocol_version' must be a whole number of at least 1.")

    return SharedNetworkConfig(network_id=network_id.strip(), protocol_version=protocol_version)
