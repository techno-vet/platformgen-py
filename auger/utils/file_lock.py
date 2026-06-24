"""Cross-platform advisory file locking helpers."""

from __future__ import annotations

from pathlib import Path

WINDOWS_LOCK_BYTES = 1


def ensure_lock_file(path: Path, mode: int = 0o666) -> None:
    """Create the lock file if needed and keep permissions permissive when supported."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        import os

        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY, mode)
        os.close(fd)
    try:
        path.chmod(mode)
    except Exception:
        pass


def acquire_file_lock(handle, blocking: bool = True) -> None:
    """Acquire an exclusive advisory lock on an open file handle."""
    if _is_windows():
        _acquire_windows_lock(handle, blocking=blocking)
        return

    import fcntl

    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    fcntl.flock(handle, flags)


def release_file_lock(handle) -> None:
    """Release an advisory lock on an open file handle."""
    if _is_windows():
        _release_windows_lock(handle)
        return

    import fcntl

    fcntl.flock(handle, fcntl.LOCK_UN)


def probe_file_lock(handle) -> bool:
    """Return True when the file lock is currently available."""
    try:
        acquire_file_lock(handle, blocking=False)
    except BlockingIOError:
        return False
    else:
        release_file_lock(handle)
        return True


def _is_windows() -> bool:
    import os

    return os.name == "nt"


def _acquire_windows_lock(handle, blocking: bool) -> None:
    import msvcrt

    _prepare_windows_lock_file(handle)
    handle.seek(0)
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    try:
        msvcrt.locking(handle.fileno(), mode, WINDOWS_LOCK_BYTES)
    except OSError as exc:
        raise BlockingIOError(str(exc)) from exc


def _release_windows_lock(handle) -> None:
    import msvcrt

    _prepare_windows_lock_file(handle)
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, WINDOWS_LOCK_BYTES)


def _prepare_windows_lock_file(handle) -> None:
    handle.seek(0, 2)
    if handle.tell() < WINDOWS_LOCK_BYTES:
        handle.write("\0" * WINDOWS_LOCK_BYTES)
        handle.flush()
