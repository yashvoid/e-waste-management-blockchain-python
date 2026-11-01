import json
import os
import shutil
from pathlib import Path

from app.storage.errors import StorageError

BLOCKS_FILE_NAME = "blocks.jsonl"
TIP_FILE_NAME = "canonical_tip.json"
RECOVERY_DIR_NAME = "recovery"


def read_complete_records(data_dir: Path) -> list[str]:
    path = data_dir / BLOCKS_FILE_NAME
    if not path.exists():
        return []
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        data = _recover_incomplete_tail(data_dir, path, data)
    return split_record_text(_decode_text(data))


def split_record_text(text: str) -> list[str]:
    if not text:
        return []
    if not text.endswith("\n"):
        raise StorageError("The block file ends with an incomplete record.")
    return text[:-1].split("\n")


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError("The block file contains text that is not valid UTF-8.") from exc


def _recover_incomplete_tail(data_dir: Path, path: Path, data: bytes) -> bytes:
    complete_length = data.rfind(b"\n") + 1
    recovery_dir = data_dir / RECOVERY_DIR_NAME
    recovery_dir.mkdir(exist_ok=True)
    index = _next_free_index(recovery_dir)
    shutil.copy2(path, recovery_dir / f"blocks-before-recovery-{index}.jsonl")
    (recovery_dir / f"incomplete-tail-{index}.bin").write_bytes(data[complete_length:])
    with open(path, "r+b") as handle:
        handle.truncate(complete_length)
        handle.flush()
        os.fsync(handle.fileno())
    return data[:complete_length]


def _next_free_index(recovery_dir: Path) -> int:
    index = 1
    while (recovery_dir / f"blocks-before-recovery-{index}.jsonl").exists():
        index += 1
    return index


def append_record(data_dir: Path, line: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / BLOCKS_FILE_NAME, "ab") as handle:
        handle.write(line.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def read_tip_metadata(data_dir: Path) -> dict[str, object] | None:
    path = data_dir / TIP_FILE_NAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(raw, dict) or set(raw) != {"tip_hash", "height"}:
        return None
    return raw


def write_tip_metadata(data_dir: Path, tip_hash: str, height: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    temporary = data_dir / f"{TIP_FILE_NAME}.tmp"
    payload = json.dumps({"tip_hash": tip_hash, "height": height}, sort_keys=True).encode("utf-8")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, data_dir / TIP_FILE_NAME)
