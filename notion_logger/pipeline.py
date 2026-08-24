"""공통 처리 파이프라인 — 세션당 페이지 1개 구조 (브랜치: session-per-page)

master 브랜치는 '턴당 페이지 1개' 구조다. 이 브랜치는 같은 세션이면
같은 페이지에 턴을 계속 append 하는 대안 구현이다.

hook 진입점(run.py)과 테스트 스크립트가 함께 쓰는 핵심 흐름:

    payload → 어댑터 감지 → 전체 턴 파싱
            → state로 '이미 기록한 위치' 확인 → 새 턴만 처리
                - 첫 턴: 페이지 생성 (속성 포함)
                - 이후 턴: 같은 페이지에 append + 속성 갱신
            → state 갱신

state가 유실된 경우 Session ID 컬럼으로 기존 페이지를 재탐색해서
이어쓰기를 복구한다.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from . import notion_api, render, state
from .adapters import detect_adapter
from .adapters.base import Context

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_payload(payload: Dict[str, Any]) -> Optional[str]:
    """payload 1건을 처리하고 마지막으로 건드린 page id를 반환한다.

    실패 시 None (절대 예외를 밖으로 던지지 않는다 — hook 방해 금지).
    """
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
        page_id = record.get("page_id")

        turns = adapter.parse_turns(payload)

        # --- 2. state 유실 시 노션에서 페이지 재탐색 ---
        # 재탐색에 성공했다는 것 = 그 세션의 기존 기록이 이미 노션에 있다는 뜻.
        # 이 경우 트랜스크립트 전체를 다시 기록하면 중복이 생기므로,
        # 현재 시점까지의 내용은 건너뛰고 '앞으로 새로 생기는 턴'만 기록한다.
        if page_id is None:
            found = notion_api.find_page_by_session(ctx.session_id)
            if found:
                page_id = found
                if turns:
                    last_offset = max(last_offset, turns[-1][0])
                log.info("기존 페이지 재탐색 성공(기존 내용 건너뜀): %s", page_id)

        pending = [(end, t) for end, t in turns if end > last_offset]

        if not pending:
            log.info("새 턴 없음: %s (offset=%d)", key, last_offset)
            return page_id

        schema = notion_api.database_schema()
        if not schema:
            log.error("DB 스키마 조회 실패")
            return None

        # --- 3. 새 턴을 같은 페이지에 이어서 기록 ---
        for end, turn in pending:
            turn_number = turn_count + 1
            stats = render.collect_statistics(turn.events)
            status = render.infer_status(turn.events)
            work_type = render.infer_work_type(turn)

            blocks = render.build_page_blocks(
                ctx, turn, turn_number,
                include_toc=(page_id is None),  # 새 페이지일 때만 최상단 목차
            )

            if page_id is None:
                properties = render.build_properties(
                    schema, ctx, turn, stats, status, work_type,
                    turn_number=turn_number,
                )
                new_page_id = notion_api.create_page(properties, blocks)
                if not new_page_id:
                    log.error("페이지 생성 실패: %s", key)
                    return None
                page_id = new_page_id
                log.info("페이지 생성: %s turn=%d", key, turn_number)
            else:
                if not notion_api.append_blocks(page_id, blocks):
                    log.error("턴 추가 실패: %s turn=%d", key, turn_number)
                    return None
                notion_api.update_page_properties(page_id, {
                    **({"Turns": {"number": turn_number}} if "Turns" in schema else {}),
                    **({"Last At": {"date": {"start": _now_iso()}}} if "Last At" in schema else {}),
                    **({"Status": {"select": {"name": status}}} if "Status" in schema else {}),
                })
                log.info("턴 추가: %s turn=%d", key, turn_number)

            turn_count = turn_number
            state.update(key, page_id=page_id, offset=end, turns=turn_count)

        return page_id

    except Exception:
        log.exception("처리 중 예외 발생")
        return None
