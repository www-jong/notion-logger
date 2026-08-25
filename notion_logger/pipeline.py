"""공통 처리 파이프라인 — v0.7 (턴당 페이지 1개 구조)

hook 진입점(run.py)과 테스트 스크립트가 함께 쓰는 핵심 흐름:

    payload → 어댑터 감지 → 전체 턴 파싱
            → state로 '이미 기록한 위치' 확인 → 새 턴만 처리
            → 턴 1개당 페이지 1개 생성

세션 전체 흐름은 노션 DB에서
    Session ID 오름차순 + Turns 오름차순 정렬
로 다시 볼 수 있다.

state가 유실된 경우 Session ID 컬럼으로 기존 페이지를 재탐색해
기존 내용은 건너뛰고(중복 방지) 이후 턴부터 기록한다.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import notion_api, render, state
from .adapters import detect_adapter, get_adapter
from .adapters.base import Adapter, Context

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_payload(payload: Dict[str, Any], agent_name: str = "") -> Optional[str]:
    """payload 1건을 처리하고 마지막으로 만든 page id를 반환한다.

    agent_name이 주어지면 그 어댑터를 바로 쓰고(hook 설정 지정 경로),
    없으면 payload 지문으로 감지한다.
    실패 시 None (절대 예외를 밖으로 던지지 않는다 — hook 방해 금지).
    """
    adapter = get_adapter(agent_name)
    if adapter is None and agent_name:
        log.warning("알 수 없는 에이전트 이름 '%s' — 지문 감지로 폴백", agent_name)
    if adapter is None:
        adapter = detect_adapter(payload)
    if adapter is None:
        log.warning("맞는 어댑터 없음. payload keys=%s", sorted(payload.keys()))
        return None

    try:
        ctx: Context = adapter.context(payload)
        key = state.session_key(ctx.agent, ctx.project, ctx.session_id)

        # --- 1. 새로 기록할 턴 걸러내기 ---
        record = state.get(key) or {}
        last_offset = record.get("offset", 0)
        turn_count = record.get("turns", 0)

        turns = adapter.parse_turns(payload)

        # --- 2. state 유실 시 중복 방지 ---
        # 로컬 state가 없는데 해당 세션의 페이지가 노션에 이미 있다면
        # 그 세션의 현재까지 내용은 이미 기록된 것이므로 전부 건너뛴다.
        if not record:
            found = notion_api.find_page_by_session(ctx.session_id)
            if found:
                if turns:
                    last_offset = turns[-1][0]
                log.info("기존 세션 발견 — 기존 내용 건너뜀: %s", key)
                state.update(key, offset=last_offset,
                             turns=turn_count, session_seen=True)
                return None

        pending = [(end, t) for end, t in turns if adapter.is_new(end, last_offset)]

        if not pending:
            log.info("새 턴 없음: %s (offset=%d)", key, last_offset)
            return None

        schema = notion_api.database_schema()
        if not schema:
            log.error("DB 스키마 조회 실패")
            return None

        # --- 3. 새 턴 각각을 페이지로 생성 ---
        last_page_id = None

        for end, turn in pending:
            turn_number = turn_count + 1
            stats = render.collect_statistics(turn.events)
            status = render.infer_status(turn.events)
            work_type = render.infer_work_type(turn)

            properties = render.build_properties(
                schema, ctx, turn, stats, status, work_type,
                turn_number=turn_number,
            )
            blocks = render.build_page_blocks(ctx, turn, turn_number)

            page_id = notion_api.create_page(properties, blocks)
            if not page_id:
                log.error("페이지 생성 실패: %s turn=%d", key, turn_number)
                return last_page_id

            log.info("페이지 생성: %s turn=%d tools=%d",
                     key, turn_number, stats["tool_calls"])

            turn_count = turn_number
            last_offset = end
            last_page_id = page_id

            # 턴 하나 성공할 때마다 state 저장 (중간에 죽어도 이어쓰기 가능)
            state.update(key, offset=last_offset, turns=turn_count)

        return last_page_id

    except Exception:
        log.exception("처리 중 예외 발생")
        return None
