#!/usr/bin/env python3
"""
노션 API 연결 테스트 스크립트 — v0.3

하는 일:
    1. .env 설정을 읽고 유효성 확인
    2. 테스트 페이지 1개를 DB에 생성 (컬럼별 샘플 값 채움)
    3. 생성된 페이지 URL 출력 → 노션에서 직접 눈으로 확인용

성공 판정 기준:
    - 콘솔에 페이지 URL이 출력됨
    - 노션 'new db'에서 "[TEST]" 제목의 행이 보이고
      각 컬럼(select/number/date/rich_text)에 값이 채워져 있음
"""

import socket
import sys
from datetime import datetime, timezone

import requests

from notion_logger import config


def build_test_properties() -> dict:
    """테스트용 속성값 구성 — DB의 모든 컬럼 타입을 한 번씩 검증."""

    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        # title: DB 제목 컬럼 이름은 노션 UI에서 만든 그대로("이름") 사용
        "이름": {
            "title": [
                {"text": {"content": f"[TEST] 연결 테스트 {now_iso[:16]}"}}
            ]
        },
        "Agent": {"select": {"name": "Test"}},
        "Host/Device": {"select": {"name": socket.gethostname()}},
        "Project": {"select": {"name": "notion-logger"}},
        "Status": {"select": {"name": "Success"}},
        "Work Type": {"select": {"name": "Development"}},
        "Session ID": {"rich_text": [{"text": {"content": "test-session-001"}}]},
        "Created At": {"date": {"start": now_iso}},
        "Last At": {"date": {"start": now_iso}},
        "Turns": {"number": 1},
        "Tool Calls": {"number": 2},
        "Commands": {"number": 1},
        "Files Read": {"number": 3},
        "Files Changed": {"number": 0},
        "Errors": {"number": 0},
    }


def create_test_page() -> str | None:
    """테스트 페이지 생성. 성공 시 페이지 ID 반환."""
    res = requests.post(
        f"{config.NOTION_API_BASE}/pages",
        headers={
            "Authorization": f"Bearer {config.api_key()}",
            "Content-Type": "application/json",
            "Notion-Version": config.NOTION_VERSION,
        },
        json={
            "parent": {"database_id": config.database_id()},
            "properties": build_test_properties(),
        },
        timeout=15,
    )

    if res.status_code not in (200, 201):
        print(f"[오류] 페이지 생성 실패 ({res.status_code}): {res.text[:500]}")
        return None

    return res.json().get("id")


def main() -> None:
    config.load_env()

    if not config.is_configured():
        print("[오류] .env 에 NOTION_API_KEY / NOTION_DATABASE_ID 를 설정하세요.")
        sys.exit(1)

    page_id = create_test_page()
    if page_id is None:
        sys.exit(1)

    url = f"https://www.notion.so/{page_id.replace('-', '')}"
    print("[성공] 테스트 페이지가 생성되었습니다.")
    print(f"확인: {url}")


if __name__ == "__main__":
    main()
