"""공통 처리 파이프라인 — v0.8 (턴 번호 기반)

hook 진입점(run.py)과 테스트 스크립트가 함께 쓰는 핵심 흐름:

    payload → 어댑터 감지 → 총 턴 수 게이트(저비용)
            → 노션에서 기록된 Turns 조회   ← 유일한 진실원천
            → 미기록 턴만 파싱해 페이지 생성

로컬 state를 쓰지 않는다. "노션에 그 번호 페이지가 있는가"가
중복 판정의 전부이므로 트랜스크립트 재작성(컴팩션 등)에도 영향 없음.

세션 전체 흐름은 노션 DB에서
    Session ID 오름차순 + Turns 오름차순 정렬
로 다시 볼 수 있다.
"""

import logging
from typing import Any, Dict, Optional

from . import notion_api, render
from .adapters import detect_adapter, get_adapter
from .adapters.base import Context

log = logging.getLogger(__name__)


def process_payload(payload: Dict[str, Any], agent_name: str = "") -> Optional[str]:
    """payload 1건을 처리하고 마지막으로 만든 page id를 반환한다.

    agent_name이 주어지면 그 어댑터를 바로 쓰고(hook 설정 지정 경로),
    없으면 payload 지문으로 감지한다.
    실패 시 None (절대 예외를 밖으로 던지지 않는다 — hook 방해 금지).
    """
    try:
        adapter = get_adapter(agent_name)
        if adapter is None and agent_name:
            log.warning("알 수 없는 에이전트 이름 '%s' — 지문 감지로 폴백", agent_name)
        if adapter is None:
            adapter = detect_adapter(payload)
        if adapter is None:
            log.warning("맞는 어댑터 없음. payload keys=%s", sorted(payload.keys()))
            return None

        ctx: Context = adapter.context(payload)

        # --- 1. 게이트: 새 턴 가능성이 있는지 저비용 확인 ---
        total = adapter.count_turns(payload)
        if total <= 0:
            log.info("턴 없음: %s", ctx.session_id)
            return None

        # --- 2. 진실원천 조회: 노션에 기록된 턴 번호 ---
        recorded = notion_api.recorded_turn_numbers(ctx.session_id)
        missing = [n for n in range(1, total + 1) if n not in recorded]
        if not missing:
            log.info("새 턴 없음: %s (%d턴 모두 기록됨)", ctx.session_id, total)
            return None

        schema = notion_api.database_schema()
        if not schema:
            log.error("DB 스키마 조회 실패")
            return None

        # --- 3. 미기록 턴만 파싱해 페이지 생성 ---
        turns = adapter.parse_turns(payload, set(missing))
        turns = sorted((t for t in turns if t.number in set(missing)),
                       key=lambda t: t.number)
        if not turns:
            log.info("미기록 턴 파싱 결과 없음: %s (게이트 과대 계상)", ctx.session_id)
            return None

        last_page_id = None
        for turn in turns:
            stats = render.collect_statistics(turn.events)
            status = render.infer_status(turn.events)
            work_type = render.infer_work_type(turn)

            properties = render.build_properties(
                schema, ctx, turn, stats, status, work_type,
                turn_number=turn.number,
            )
            blocks = render.build_page_blocks(ctx, turn, turn.number)

            page_id = notion_api.create_page(properties, blocks)
            if not page_id:
                log.error("페이지 생성 실패: %s turn=%d", ctx.session_id, turn.number)
                return last_page_id

            log.info("페이지 생성: %s/%s turn=%d tools=%d",
                     ctx.agent, ctx.project, turn.number, stats["tool_calls"])
            last_page_id = page_id

        return last_page_id

    except Exception:
        log.exception("처리 중 예외 발생")
        return None
