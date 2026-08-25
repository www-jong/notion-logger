"""크로스 플랫폼 파일 락 모듈 (Windows / macOS / Linux 지원).

외부 의존성 없이 표준 라이브러리(POSIX: fcntl, Windows: msvcrt)를 사용하여
프로세스 간 단일 실행(Single Flight) 파일 락을 구현합니다.
"""

import os
from pathlib import Path
from typing import Any, Optional

if os.name == "nt":
    import msvcrt

    def _lock_handle(handle: Any) -> bool:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, PermissionError):
            return False

    def _unlock_handle(handle: Any) -> None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _lock_handle(handle: Any) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock_handle(handle: Any) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def acquire_lock(lock_path: Path | str) -> Optional[Any]:
    """논블로킹 배타적 락을 획득합니다. 이미 잠겨있으면 None을 반환합니다.

    Windows msvcrt의 경우 파일의 1바이트를 잠그므로, 파일에 최소 1바이트를 확보합니다.
    """
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if not path.exists() or path.stat().st_size == 0:
            try:
                with open(path, "a+b") as init_f:
                    if init_f.tell() == 0:
                        init_f.write(b"0")
            except OSError:
                pass

        handle = open(path, "r+b")
        if _lock_handle(handle):
            return handle
        handle.close()
        return None
    except OSError:
        return None


def release_lock(handle: Optional[Any]) -> None:
    """락을 해제하고 파일 핸들을 닫습니다."""
    if handle is None:
        return
    try:
        _unlock_handle(handle)
    finally:
        try:
            handle.close()
        except OSError:
            pass


class FileLock:
    """컨텍스트 매니저 인터페이스."""

    def __init__(self, lock_path: Path | str):
        self.lock_path = Path(lock_path)
        self.handle: Optional[Any] = None

    def __enter__(self) -> Optional[Any]:
        self.handle = acquire_lock(self.lock_path)
        return self.handle

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle is not None:
            release_lock(self.handle)
            self.handle = None
