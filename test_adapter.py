#!/usr/bin/env python3
"""
어댑터 파이프라인 테스트 스크립트 — v0.5b

안티그래비티를 다시 켤 필요 없이,
debug_hook이 저장해둔 payload 파일을 재사용해 전체 흐름을 검증한다.

    1. .gemini/hooks/test/tmp/hook_payload_*.json 중 가장 최근 것 로드
    2. 그 안의 stdin_raw(실제 hook payload)를 꺼냄
    3. process_payload() 실행 → 실제 노션 페이지 생성

성공 판정:
    - 출력된 노션 URL의 페이지에서
      사용자 요청 / 작업 내역 / 최종 응답 확인
"""

import glob
import json
import sys
from pathlib import Path

from notion_logger import config
from notion_logger.pipeline import process_payload

# debug_hook 이 저장한 payload 위치 (환경에 따라 경로가 다르면 수정)
CAPTURE_DIR = Path.home() / ".gemini" / "hooks" / "test" / "tmp"


def load_latest_capture() -> dict | None:
    """가장 최근 payload 캡처에서 실제 hook JSON을 꺼낸다."""
    files = sorted(
        CAPTURE_DIR.glob("hook_payload_*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        print(f"[오류] 캡처 파일 없음: {CAPTURE_DIR}")
        return None

    latest = files[-1]
    print(f"사용 캡처: {latest.name}")

    report = json.loads(latest.read_text(encoding="utf-8"))
    raw = report.get("stdin_raw", "")
    if not raw.strip():
        print("[오류] 캡처의 stdin_raw가 비어있음")
        return None

    return json.loads(raw)


def main() -> None:
    config.load_env()
    if not config.is_configured():
        print("[오류] .env 설정 필요")
        sys.exit(1)

    payload = load_latest_capture()
    if payload is None:
        sys.exit(1)

    print(f"payload keys: {sorted(payload.keys())}")

    # --- 1회차: 세션 기록 기록 ---
    page_id = process_payload(payload)
    if page_id is None:
        # 새 턴이 없으면(이미 최신까지 기록됨) 정상적으로 None 반환
        print("[결과] 생성된 페이지 없음 (이미 최신까지 기록됐거나 실패)")
        print("       자세한 내용은 tmp/logger.log 확인")
        sys.exit(0)

    url = f"https://www.notion.so/{page_id.replace('-', '')}"
    print("[성공] 세션 기록 페이지 처리 완료")
    print(f"확인: {url}")

    # --- 2회차: 같은 payload 재처리 → 중복 기록 없음 확인 ---
    # 클래식 모드(턴당 페이지)에서는 새 턴이 없으면 None 반환과 state 갱신 없음이 정상.
    page_id_2 = process_payload(payload)
    if page_id_2 is None:
        print("[검증] 재실행 결과: 새 페이지 생성 없음 (정상 — state로 중복 방지)")
    else:
        print("[비정상] 재실행에서 중복 페이지 생성됨:", page_id_2)


if __name__ == "__main__":
    main()
