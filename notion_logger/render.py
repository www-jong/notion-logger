"""Turn → 노션 속성/블록 렌더링.

- 속성: DB에 실제 존재하는 컬럼만 채운다 (스키마 유연 대응)
- 블록: 사용자 요청 → 작업 내역(툴 호출/결과/에러) → 최종 응답 순서
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from . import notion_api
from .adapters.base import TOOL_CATEGORY_ICONS, Context, Turn
from .md2notion import markdown_to_notion_blocks


# ------------------------------------------------------------
# 통계 / 분류
# ------------------------------------------------------------

def collect_statistics(events) -> Dict[str, int]:
    """턴 내 활동 통계 집계."""
    tool_calls = [e for e in events if e.kind == "tool_call"]
    return {
        "tool_calls": len(tool_calls),
        "commands": len([e for e in tool_calls if e.category == "command"]),
        "files_read": len([e for e in tool_calls if e.category == "file_read"]),
        "files_changed": len([e for e in tool_calls if e.category == "file_edit"]),
        "errors": len([e for e in events if e.kind == "error"]),
    }


def infer_status(events) -> str:
    has_error = any(e.kind == "error" for e in events)
    return "Failed" if has_error else "Success"


def infer_work_type(turn: Turn) -> str:
    """요청 텍스트 키워드로 작업 유형 추정."""
    text = turn.user_request.lower()

    if any(k in text for k in ("수정", "고쳐", "오류", "에러", "fix", "bug", "debug")):
        return "Debug"
    if any(k in text for k in ("구현", "만들", "추가", "작성", "implement", "create")):
        return "Development"
    if any(k in text for k in ("분석", "확인", "찾아", "설명", "analyze", "review")):
        return "Analysis"
    if any(e.category == "file_edit" for e in turn.events):
        return "Development"
    return "Other"


# ------------------------------------------------------------
# 속성 생성
# ------------------------------------------------------------

def _truncate(text: str, limit: int = 2000) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


# 페이지 제목(요청 첫 줄) 최대 길이
TITLE_MAX_CHARS = 50


def build_properties(schema: Dict[str, Any], ctx: Context,
                     turn: Turn, stats: Dict[str, int],
                     status: str, work_type: str,
                     turn_number: int = 1) -> Dict[str, Any]:
    """DB 스키마를 보고 '존재하는 컬럼만' 값으로 채운다."""

    props: Dict[str, Any] = {}

    def put(name: str, value: Dict[str, Any]) -> None:
        if name in schema:
            props[name] = value

    # 제목 컬럼은 이름이 무엇이든(title 타입) 자동 감지해서 사용.
    # 요청 첫 줄만 자르지 않고 넣으면 파일 경로 등으로 지나치게 길어지므로
    # 앞 50자까지만 넣는다.
    title_name = notion_api.title_property_name(schema)
    if title_name:
        first_line = turn.user_request.splitlines()[0].strip() if turn.user_request else "(빈 요청)"
        if len(first_line) > TITLE_MAX_CHARS:
            first_line = first_line[:TITLE_MAX_CHARS] + "…"
        props[title_name] = {
            "title": [{"text": {"content": _truncate(first_line, 200)}}]
        }

    now_iso = datetime.now(timezone.utc).isoformat()

    put("Agent", {"select": {"name": ctx.agent}})
    put("Host/Device", {"select": {"name": __import__("socket").gethostname()}})
    put("Project", {"select": {"name": ctx.project}})
    put("Status", {"select": {"name": status}})
    put("Work Type", {"select": {"name": work_type}})
    put("Session ID", {"rich_text": [{"text": {"content": _truncate(ctx.session_id)}}]})
    put("Created At", {"date": {"start": now_iso}})
    put("Last At", {"date": {"start": now_iso}})

    for name, value in (
        ("Turns", turn_number),
        ("Tool Calls", stats["tool_calls"]),
        ("Commands", stats["commands"]),
        ("Files Read", stats["files_read"]),
        ("Files Changed", stats["files_changed"]),
        ("Errors", stats["errors"]),
    ):
        put(name, {"number": value})

    return props


# ------------------------------------------------------------
# 본문 블록 생성
# ------------------------------------------------------------

def _code(text: str, lang: str = "plain text") -> List[Dict[str, Any]]:
    return markdown_to_notion_blocks(f"```{lang}\n{text}\n```")


def _event_blocks(ev, index: int) -> List[Dict[str, Any]]:
    """툴 호출 1건 → 헤딩 + 상세 블록들."""
    icon = TOOL_CATEGORY_ICONS.get(ev.category, "🛠️")
    blocks = markdown_to_notion_blocks(f"### {icon} {ev.tool}")

    detail_lines = []
    if ev.summary:
        detail_lines.append(f"- 요약: {ev.summary}")
    if ev.path:
        detail_lines.append(f"- 경로: `{ev.path}`")
    if ev.command:
        detail_lines.append("- 명령:")
        blocks += markdown_to_notion_blocks("\n".join(detail_lines))
        blocks += _code(ev.command, "shell")
    elif detail_lines:
        blocks += markdown_to_notion_blocks("\n".join(detail_lines))

    # 나머지 인자 중 표시 안 된 것이 있으면 코드블록으로
    shown = {"summary", "command", "cmd", *(
        k for k in ev.args if k.lower() in ("path", "filepath", "target",
                                            "absolutepath", "cwd")
    )}
    rest = {k: v for k, v in ev.args.items() if k not in shown}
    if rest:
        try:
            blocks += _code(json.dumps(rest, ensure_ascii=False, indent=2)[:4000], "json")
        except (TypeError, ValueError):
            pass

    return blocks


TOC_BLOCK = {
    # 노션의 /목차 에 해당하는 블록.
    # 아래 heading(#, ##)들을 자동으로 모아 목차를 만들어준다.
    "object": "block",
    "type": "table_of_contents",
    "table_of_contents": {"color": "default"},
}


def build_page_blocks(ctx: Context, turn: Turn, turn_number: int = 1,
                      include_toc: bool = False) -> List[Dict[str, Any]]:
    """턴 1개 → 본문 블록 배열.

    같은 세션의 턴들이 한 페이지에 계속 append 되므로
    매 턴마다 '# 🔄 Turn N' 헤딩으로 구간을 표시한다.
    include_toc: 새 페이지를 만들 때 True — 최상단에 목차 배치.
    """
    blocks: List[Dict[str, Any]] = []

    if include_toc:
        blocks.append(TOC_BLOCK)

    # 턴 헤딩에 요청 내용을 붙이면, 노션 목차가 곧
    # '턴별 대화 목록' 역할을 해서 바로바로 점프할 수 있다.
    request_headline = (turn.user_request or "").splitlines()[0][:40] if turn.user_request else ""
    heading = f"# 🔄 Turn {turn_number}" + (f" — {request_headline}" if request_headline else "")
    blocks += markdown_to_notion_blocks(heading)

    # --- 사용자 요청 ---
    blocks += markdown_to_notion_blocks("## 📝 사용자 요청")
    blocks += markdown_to_notion_blocks(turn.user_request or "(없음)")

    # --- 작업 내역 ---
    blocks += markdown_to_notion_blocks("## ⚙️ 작업 내역")

    call_index = 0
    pending_results: List[Any] = []

    for ev in turn.events:
        if ev.kind == "tool_call":
            call_index += 1
            blocks += _event_blocks(ev, call_index)
        else:
            pending_results.append(ev)

    # 결과/에러는 마지막에 한꺼번에
    results = [e for e in pending_results if e.kind == "tool_result"]
    errors = [e for e in pending_results if e.kind == "error"]

    if results:
        blocks += markdown_to_notion_blocks("# 📤 실행 결과")
        for r in results[:10]:  # 너무 많으면 앞 10개만
            blocks += _code(r.result)
    if errors:
        blocks += markdown_to_notion_blocks("# ❌ 에러")
        for er in errors[:10]:
            blocks += _code(er.result)

    if call_index == 0 and not results and not errors:
        blocks += markdown_to_notion_blocks("(툴 호출 없음 — 바로 응답한 턴)")

    # --- 최종 응답 (마크다운 그대로 변환) ---
    blocks += markdown_to_notion_blocks("## 📝 최종 응답")
    response_blocks = markdown_to_notion_blocks(turn.final_response or "(응답 없음)")
    blocks += response_blocks or markdown_to_notion_blocks("(변환된 블록 없음)")

    blocks += markdown_to_notion_blocks("---")

    return blocks
