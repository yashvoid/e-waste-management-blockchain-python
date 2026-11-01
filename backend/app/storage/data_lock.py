import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from app.storage.errors import StorageError

LOCK_FILE_NAME = "node.lock"


@contextmanager
def exclusive_data_lock(data_dir: Path) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = open(data_dir / LOCK_FILE_NAME, "a+b")
    try:
        _acquire(handle)
    except OSError as exc:
        handle.close()
        raise StorageError("Another process is already using this node's blockchain storage.") from exc
    try:
        yield
    finally:
        _release(handle)
        handle.close()


def _acquire(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
