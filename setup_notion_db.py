#!/usr/bin/env python3
"""
노션 데이터베이스 컬럼(속성) 자동 생성 스크립트 — v0.2

하는 일:
    1. 저장소 루트의 .env 파일에서 NOTION_API_KEY / NOTION_DATABASE_ID 읽기
    2. 대상 데이터베이스에 아래 컬럼들이 없으면 자동으로 추가 (PATCH)
       - 이미 있으면 그대로 둠 (몇 번을 실행해도 안전, 멱등성 보장)

사용법:
    python setup_notion_db.py

주의:
    - DB의 title(제목) 컬럼은 노션에서 기본 생성되는 것을 그대로 사용.
    - 실행 후 현재 DB 스키마를 출력해서 눈으로 확인할 수 있게 함.
"""

import json
import os
import sys
from pathlib import Path

import requests

# ------------------------------------------------------------
# 설정 로딩: .env 파일 (KEY=VALUE 형식, # 주석 지원)
# ------------------------------------------------------------

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def load_env() -> None:
    """.env 파일을 읽어 환경변수로 등록한다. (이미 등록된 값은 덮어쓰지 않음)"""
    env_path = Path(__file__).parent / ".env"

    if not env_path.exists():
        print(f"[오류] .env 파일이 없습니다: {env_path}")
        sys.exit(1)

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_config() -> tuple[str, str]:
    api_key = os.getenv("NOTION_API_KEY", "")
    database_id = os.getenv("NOTION_DATABASE_ID", "").replace("-", "")

    if not api_key or not database_id:
        print("[오류] .env 에 NOTION_API_KEY / NOTION_DATABASE_ID 를 모두 설정하세요.")
        sys.exit(1)

    return api_key, database_id


# ------------------------------------------------------------
# 생성할 컬럼 정의
# ------------------------------------------------------------

def build_properties_schema() -> dict:
    """노션 DB에 추가할 컬럼 정의.

    select 컬럼은 선택지(options)를 미리 넣어두면 노션 UI에서 색깔 태그로 보임.
    options를 비워두면 나중에 어떤 값이든 자유롭게 추가 가능.
    """
    return {
        # --- 분류용 select ---
        "Agent": {"select": {}},  # Antigravity / opencode / ... (자유 추가)
        "Host/Device": {"select": {}},  # PC 이름
        "Project": {"select": {}},  # 프로젝트명
        "Status": {
            "select": {
                "options": [
                    {"name": "Success", "color": "green"},
                    {"name": "Failed", "color": "red"},
                ]
            }
        },
        "Work Type": {
            "select": {
                "options": [
                    {"name": "Development", "color": "blue"},
                    {"name": "Debug", "color": "orange"},
                    {"name": "Analysis", "color": "purple"},
                    {"name": "Other", "color": "gray"},
                ]
            }
        },
        # --- 세션 추적 ---
        "Session ID": {"rich_text": {}},  # 세션 고유키 (페이지 재탐색용)
        # --- 시간 ---
        "Created At": {"date": {}},  # 첫 턴 시각
        "Last At": {"date": {}},  # 마지막 턴 시각
        # --- 통계 number ---
        "Turns": {"number": {"format": "number"}},
        "Tool Calls": {"number": {"format": "number"}},
        "Commands": {"number": {"format": "number"}},
        "Files Read": {"number": {"format": "number"}},
        "Files Changed": {"number": {"format": "number"}},
        "Errors": {"number": {"format": "number"}},
    }


# ------------------------------------------------------------
# Notion API 호출
# ------------------------------------------------------------

def notion_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def fetch_database(api_key: str, database_id: str) -> dict | None:
    """DB 정보 조회. 실패 시 None."""
    res = requests.get(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=notion_headers(api_key),
        timeout=15,
    )
    if res.status_code != 200:
        print(f"[오류] DB 조회 실패 ({res.status_code}): {res.text[:500]}")
        return None
    return res.json()


def update_database(api_key: str, database_id: str, properties: dict) -> bool:
    """DB에 컬럼 추가 (PATCH). 없는 컬럼만 추가됨."""
    res = requests.patch(
        f"{NOTION_API_BASE}/databases/{database_id}",
        headers=notion_headers(api_key),
        json={"properties": properties},
        timeout=15,
    )
    if res.status_code != 200:
        print(f"[오류] DB 수정 실패 ({res.status_code}): {res.text[:500]}")
        return False
    return True


# ------------------------------------------------------------
# 메인
# ------------------------------------------------------------

def main() -> None:
    load_env()
    api_key, database_id = get_config()

    db = fetch_database(api_key, database_id)
    if db is None:
        sys.exit(1)

    existing = set(db.get("properties", {}).keys())
    title_prop = next(
        (name for name, prop in db["properties"].items() if prop["type"] == "title"),
        None,
    )
    print(f"대상 DB   : {db.get('title', [{}])[0].get('plain_text', '(제목없음)')}")
    print(f"제목 컬럼 : {title_prop} (기존 유지)")
    print(f"기존 컬럼 : {sorted(existing)}")

    wanted = build_properties_schema()
    missing = {name: schema for name, schema in wanted.items() if name not in existing}

    if not missing:
        print("\n추가할 컬럼 없음 — 이미 모두 존재합니다.")
    else:
        print(f"\n컬럼 {len(missing)}개 추가 중: {sorted(missing)}")
        if not update_database(api_key, database_id, missing):
            sys.exit(1)
        print("추가 완료.")

    # 최종 스키마 확인 출력
    db = fetch_database(api_key, database_id)
    if db is None:
        sys.exit(1)

    print("\n=== 최종 DB 스키마 ===")
    for name, prop in sorted(db["properties"].items()):
        extra = ""
        if prop["type"] == "select":
            options = [o["name"] for o in prop["select"].get("options", [])]
            extra = f" [{', '.join(options)}]" if options else ""
        print(f"  {name:<14} ({prop['type']}){extra}")


if __name__ == "__main__":
    main()
