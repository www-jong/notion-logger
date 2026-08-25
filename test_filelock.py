#!/usr/bin/env python3
"""
크로스 플랫폼 파일 락 유닛 테스트 스크립트.

Windows(msvcrt)와 POSIX(fcntl) 환경에서
1. 정상 락 획득
2. 동시 실행 시 두 번째 락 차단(None 반환)
3. 락 해제 후 재획득
4. FileLock 컨텍스트 매니저 동작
을 검증한다.
"""

import sys
import tempfile
import traceback
from pathlib import Path

from notion_logger.filelock import FileLock, acquire_lock, release_lock


def test_filelock():
    with tempfile.TemporaryDirectory() as tmp_dir:
        lock_file = Path(tmp_dir) / "test.lock"

        # 1. 첫 번째 락 획득
        handle1 = acquire_lock(lock_file)
        try:
            assert handle1 is not None, "[실패] 첫 번째 락 획득 실패"
            print("[OK] 첫 번째 락 획득 성공")

            # 2. 락이 유지된 상태에서 두 번째 락 시도 -> None 반환되어야 함
            handle2 = acquire_lock(lock_file)
            assert handle2 is None, f"[실패] 중복 락이 허용됨: {handle2}"
            print("[OK] 동시/중복 락 차단 성공 (None 반환)")
        finally:
            release_lock(handle1)

        # 3. 첫 번째 락 해제 후 다시 락 시도 -> 성공해야 함
        handle3 = acquire_lock(lock_file)
        try:
            assert handle3 is not None, "[실패] 해제 후 락 재획득 실패"
            print("[OK] 락 해제 후 재획득 성공")
        finally:
            release_lock(handle3)

        # 4. FileLock 컨텍스트 매니저 검증
        with FileLock(lock_file) as ctx_handle:
            assert ctx_handle is not None, "[실패] FileLock 컨텍스트 진입 실패"
            blocked = acquire_lock(lock_file)
            assert blocked is None, "[실패] FileLock 컨텍스트 내 중복 락 차단 실패"
        print("[OK] FileLock 컨텍스트 매니저 정상 동작")

        # 5. 컨텍스트 종료 후 재획득 가능 확인
        handle4 = acquire_lock(lock_file)
        try:
            assert handle4 is not None, "[실패] 컨텍스트 종료 후 락 획득 실패"
            print("[OK] 컨텍스트 종료 후 자동 해제 확인")
        finally:
            release_lock(handle4)

    print("\n[성공] 모든 파일 락 테스트 통과!")


if __name__ == "__main__":
    try:
        test_filelock()
    except AssertionError as e:
        print(f"\n[오류] {e}")
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[예외] {e}")
        traceback.print_exc()
        sys.exit(1)
