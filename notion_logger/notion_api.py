"""노션 REST API 최소 클라이언트."""

import logging
from typing import Any, Dict, List, Optional

import requests

from . import config

log = logging.getLogger(__name__)

# 요청당 블록 수 안전 상한 (노션 API 최대 100)
BLOCK_BATCH_SIZE = 80


class NotionError(Exception):
    pass


def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {config.api_key()}",
        "Content-Type": "application/json",
        "Notion-Version": config.NOTION_VERSION,
    }


def database_schema() -> Optional[Dict[str, Any]]:
    """DB 스키마(속성 정의) 조회. 실패 시 None."""
    try:
        res = requests.get(
            f"{config.NOTION_API_BASE}/databases/{config.database_id()}",
            headers=_headers(),
            timeout=15,
        )
        if res.status_code != 200:
            log.error("DB schema 조회 실패 %s: %s", res.status_code, res.text[:300])
            return None
        return res.json().get("properties", {})
    except requests.RequestException as e:
        log.error("DB schema 요청 예외: %s", e)
        return None


def title_property_name(schema: Dict[str, Any]) -> Optional[str]:
    """DB에서 title 타입 컬럼 이름 찾기 (예: '이름')."""
    for name, prop in schema.items():
        if prop.get("type") == "title":
            return name
    return None


def create_page(properties: Dict[str, Any], blocks: List[Dict[str, Any]]) -> Optional[str]:
    """페이지 생성 + 첫 블록 배치. 성공 시 page id 반환.

    블록이 80개를 넘으면 나머지는 append_blocks로 이어 올린다.
    """
    first = blocks[:BLOCK_BATCH_SIZE]
    rest = blocks[BLOCK_BATCH_SIZE:]

    try:
        res = requests.post(
            f"{config.NOTION_API_BASE}/pages",
            headers=_headers(),
            json={
                "parent": {"database_id": config.database_id()},
                "properties": properties,
                "children": first,
            },
            timeout=30,
        )
        if res.status_code not in (200, 201):
            log.error("페이지 생성 실패 %s: %s", res.status_code, res.text[:500])
            return None
        page_id = res.json().get("id")
    except requests.RequestException as e:
        log.error("페이지 생성 예외: %s", e)
        return None

    if rest and not append_blocks(page_id, rest):
        return None

    return page_id


def append_blocks(page_id: str, blocks: List[Dict[str, Any]]) -> bool:
    """기존 페이지에 블록을 80개씩 나눠 추가."""
    for start in range(0, len(blocks), BLOCK_BATCH_SIZE):
        batch = blocks[start : start + BLOCK_BATCH_SIZE]
        try:
            res = requests.patch(
                f"{config.NOTION_API_BASE}/blocks/{page_id}/children",
                headers=_headers(),
                json={"children": batch},
                timeout=30,
            )
            if res.status_code not in (200, 201):
                log.error("블록 추가 실패 %s: %s", res.status_code, res.text[:500])
                return False
        except requests.RequestException as e:
            log.error("블록 추가 예외: %s", e)
            return False
    return True
