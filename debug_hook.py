#!/usr/bin/env python3
"""
안티그래비티 hook 연결 확인용 디버그 스크립트 — v0.5a

하는 일:
    - 에이전트 hook 실행 환경(stdin/argv/환경변수)을 파일로 덤프한다.
      (노션 전송 없음, 수신 확인 및 디버깅 목적)

저장 위치:
    tmp/hook_payload_<시각>.json   ← 실행 환경 리포트
    tmp/hook_calls.log             ← 단계별 진행 기록 (어디서 죽는지 추적)

사용법:
    1. 이 파일을 hook 설정의 command 경로에 맞게 복사해서 사용
    2. 에이전트에서 대화 1턴 진행
    3. tmp/ 폴더 확인

중요:
    - 수정은 항상 notion-logger 저장소에서 하고, 배포할 곳에는 "복사"한다.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# 저장 위치: 이 스크립트 기준 tmp/ 폴더 (.gitignore에 등록되어 있음)
OUT_DIR = Path(__file__).parent / "tmp"


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)

    now = datetime.now().strftime("%H%M%S")
    log_path = OUT_DIR / "hook_calls.log"

    def trace(msg: str) -> None:
        """단계별 진행 상황을 즉시 디스크에 기록 (죽는 지점 추적용)."""
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] "
                    f"#{now} {msg}\n")

    try:
        trace("시작")

        # --- 1단계: stdin 읽기 ---
        # 주의: sys.stdin.read() 는 Windows에서 cp949로 디코딩해버려서
        # UTF-8 JSON의 한글이 깨지고 저장 시 UnicodeEncodeError 로 죽는다.
        # 그래서 반드시 buffer(바이트)로 읽고 UTF-8로 직접 디코딩한다.
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        trace(f"stdin 읽기 완료: {len(raw)} chars")

        # --- 2단계: 진단 리포트 구성 ---
        report = {
            "argv": sys.argv,
            "cwd": str(Path.cwd()),
            "stdin_bytes": len(raw),
            "stdin_raw": raw,
            "env": {
                k: v for k, v in os.environ.items()
                # 노이즈 줄이기: 에이전트/훅 관련 변수만 추림
                if any(t in k.upper() for t in (
                    "AGENT", "GEMINI", "ANTIGRAVITY", "HOOK",
                    "SESSION", "TRANSCRIPT", "WORKSPACE", "PROJECT",
                ))
            },
        }
        trace("리포트 구성 완료")

        # --- 3단계: 저장 ---
        payload_file = OUT_DIR / f"hook_payload_{now}.json"
        payload_file.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        trace(f"저장 완료: {payload_file.name}")

    except Exception:
        import traceback
        trace("예외 발생:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
