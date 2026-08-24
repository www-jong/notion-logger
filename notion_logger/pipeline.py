"""공통 처리 파이프라인.

hook 진입점(run.py)과 테스트 스크립트가 함께 쓰는 핵심 흐름:
    payload → 어댑터 감지 → 턴 파싱 → 속성/블록 생성 → 노션 페이지 생성
"""

import logging
from typing import Any, Dict, Optional

from . import notion_api, render
from .adapters import detect_adapter

log = logging.getLogger(__name__)


def process_payload(payload: Dict[str, Any]) -> Optional[str]:
    """payload 1건을 처리해 노션 페이지를 만들고 page id를 반환한다.

    실패 시 None (절대 예외를 밖으로 던지지 않는다 — hook 방해 금지).
    """
    adapter = detect_adapter(payload)
    if adapter is None:
        log.warning("맞는 어댑터 없음. payload keys=%s", sorted(payload.keys()))
        return None

    try:
        ctx, turn = adapter.build_turn(payload)

        if not turn.user_request:
            log.info("사용자 요청을 찾지 못해 건너뜀 (%s)", ctx.session_id)
            return None

        stats = render.collect_statistics(turn.events)
        status = render.infer_status(turn.events)
        work_type = render.infer_work_type(turn)

        schema = notion_api.database_schema()
        if not schema:
            log.error("DB 스키마 조회 실패")
            return None

        properties = render.build_properties(schema, ctx, turn, stats, status, work_type)
        blocks = render.build_page_blocks(ctx, turn)

        page_id = notion_api.create_page(properties, blocks)
        if page_id:
            log.info("페이지 생성 완료: %s/%s turns=1 tools=%d",
                     ctx.project, ctx.session_id[:8], stats["tool_calls"])
        return page_id

    except Exception:
        log.exception("처리 중 예외 발생")
        return None
