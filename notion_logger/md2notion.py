"""마크다운 → 노션 블록 변환기 — v0.4

에이전트의 입출력(주로 마크다운)을 노션 페이지 본문 블록으로 변환한다.

지원 문법:
    Block:
        # ~ ###### 제목        → heading_1~3 (노션은 3단계까지만 지원)
        - / * / + 목록         → bulleted_list_item (들여쓰기 중첩 지원)
        1. 목록                → numbered_list_item
        - [ ] / - [x] 체크     → to_do
        > 인용                 → quote
        ---                    → divider
        ```언어 ... ```        → code (언어명 자동 매핑)
        | 표 | 행 |            → table (첫 줄 헤더, 정렬 구분행 자동 인식)
    Inline:
        **굵게** / __굵게__
        *기울임* / _기울임_
        ***둘다***
        `코드`
        [텍스트](url)

노션 API 제약 관련:
    - 리치 텍스트 하나의 content는 최대 2000자 → 1900자로 안전하게 분할
    - 블록당 리치 텍스트 조각 수/총 길이 제한 → 분할 처리
"""

import re
from typing import Any, Dict, List, Optional

# ------------------------------------------------------------
# 노션 API 제한값
# ------------------------------------------------------------

NOTION_TEXT_LIMIT = 1900          # rich_text content 안전 최대치 (실제 2000)
MAX_RICH_TEXT_ITEMS = 90          # 블록 하나당 리치 텍스트 조각 안전 최대치

# 코드펜스 언어명 → 노션 code block language 매핑
CODE_LANGUAGES = {
    "js": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "py": "python", "rb": "ruby",
    "sh": "shell", "bash": "shell", "zsh": "shell", "powershell": "shell",
    "yml": "yaml", "md": "markdown",
    "text": "plain text", "txt": "plain text", "plain": "plain text",
    "html": "html", "css": "css", "scss": "scss", "sql": "sql",
    "json": "json", "xml": "xml", "java": "java",
    "kt": "kotlin", "kotlin": "kotlin",
    "c": "c", "cpp": "c++", "c++": "c++", "cs": "c#", "c#": "c#",
    "go": "go", "rust": "rust", "rs": "rust", "php": "php",
    "swift": "swift", "dart": "dart",
    "dockerfile": "docker", "docker": "docker",
    "graphql": "graphql", "gql": "graphql", "diff": "diff",
}


def _normalize_language(lang: str) -> str:
    return CODE_LANGUAGES.get(lang.strip().lower(), "plain text")


# ------------------------------------------------------------
# 텍스트 분할 유틸
# ------------------------------------------------------------

def chunk_text(text: str, limit: int = NOTION_TEXT_LIMIT) -> List[str]:
    """문자열을 limit 이하 조각들로 분할.

    가능하면 줄바꿈 경계에서 자르고, 한 줄이 limit를 넘으면 강제로 자른다.
    """
    if not text:
        return []

    chunks: List[str] = []
    current = ""

    for line in text.splitlines():
        line_with_nl = line + "\n"

        # 한 줄이 제한보다 길면 강제 분할
        if len(line_with_nl) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for i in range(0, len(line), limit):
                chunks.append(line[i : i + limit])
            continue

        if current and len(current) + len(line_with_nl) > limit:
            chunks.append(current.rstrip())
            current = line_with_nl
        else:
            current += line_with_nl

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [""]


# ------------------------------------------------------------
# 인라인 마크다운 → 노션 rich_text 배열
# ------------------------------------------------------------

def parse_inline(text: str, base: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    """인라인 마크다운을 노션 rich_text 객체 배열로 변환.

    base: 상위 문맥에서 상속받는 서식(굵게 안의 기울임 등 중첩 처리용).
    """
    if base is None:
        base = {}

    result: List[Dict[str, Any]] = []

    def add(value: str, annotations: Optional[Dict[str, bool]] = None,
            href: Optional[str] = None) -> None:
        if not value:
            return
        merged = {
            "bold": False, "italic": False,
            "strikethrough": False, "underline": False, "code": False,
        }
        merged.update(base)
        if annotations:
            merged.update(annotations)
        item: Dict[str, Any] = {
            "type": "text",
            "text": {"content": value},
            "annotations": merged,
        }
        if href:
            item["text"]["link"] = {"url": href}
        result.append(item)

    buffer = ""
    i = 0

    def flush() -> None:
        nonlocal buffer
        if buffer:
            add(buffer)
            buffer = ""

    while i < len(text):
        rest = text[i:]

        # --- 링크 [label](url) ---
        m = re.match(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", rest)
        if m:
            flush()
            for sub in parse_inline(m.group(1), base):
                sub["text"]["link"] = {"url": m.group(2)}
                result.append(sub)
            i += len(m.group(0))
            continue

        # --- 인라인 코드 `...` (내부 마크다운 해석 안 함) ---
        if text[i] == "`":
            end = text.find("`", i + 1)
            if end != -1:
                flush()
                add(text[i + 1 : end], {"code": True})
                i = end + 1
                continue

        # --- 굵게+기울임 ***...*** ---
        if rest.startswith(("***", "___")):
            end = text.find(rest[:3], i + 3)
            if end != -1:
                flush()
                result.extend(
                    parse_inline(text[i + 3 : end], {**base, "bold": True, "italic": True})
                )
                i = end + 3
                continue

        # --- 굵게 **...** ---
        if rest.startswith(("**", "__")):
            end = text.find(rest[:2], i + 2)
            if end != -1:
                flush()
                result.extend(parse_inline(text[i + 2 : end], {**base, "bold": True}))
                i = end + 2
                continue

        # --- 취소선 ~~...~~ ---
        if rest.startswith("~~"):
            end = text.find("~~", i + 2)
            if end != -1:
                flush()
                result.extend(
                    parse_inline(text[i + 2 : end], {**base, "strikethrough": True})
                )
                i = end + 2
                continue

        # --- 기울임 *...* / _..._ ---
        if text[i] in ("*", "_"):
            marker = text[i]
            # snake_case 같은 단어 중간의 _ 는 기울임으로 보지 않음
            is_word_middle = (
                marker == "_"
                and 0 < i < len(text) - 1
                and text[i - 1].isalnum()
                and text[i + 1].isalnum()
            )
            if not is_word_middle:
                end = text.find(marker, i + 1)
                if end != -1 and text[i + 1 : end].strip():
                    flush()
                    result.extend(
                        parse_inline(text[i + 1 : end], {**base, "italic": True})
                    )
                    i = end + 1
                    continue

        buffer += text[i]
        i += 1

    flush()
    return result


def _split_rich_text(items: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """rich_text 배열을 노션 블록 제한(조각 수/길이)에 맞게 여러 그룹으로 분할."""
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    current_len = 0

    for item in items:
        import json as _json

        content = str(item.get("text", {}).get("content", ""))
        if not content:
            continue
        for piece in chunk_text(content, NOTION_TEXT_LIMIT):
            copy = _json.loads(_json.dumps(item))
            copy["text"]["content"] = piece

            if current and (
                len(current) >= MAX_RICH_TEXT_ITEMS
                or current_len + len(piece) > NOTION_TEXT_LIMIT
            ):
                groups.append(current)
                current, current_len = [], 0

            current.append(copy)
            current_len += len(piece)

    if current:
        groups.append(current)
    return groups


# ------------------------------------------------------------
# 블록 빌더
# ------------------------------------------------------------

def _rich_blocks(block_type: str, text: str) -> List[Dict[str, Any]]:
    """인라인 마크다운을 해석해 block_type 블록들을 만든다 (길면 여러 개)."""
    blocks = []
    for group in _split_rich_text(parse_inline(text)):
        blocks.append({
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": group},
        })
    return blocks


def _code_blocks(content: str, lang: str) -> List[Dict[str, Any]]:
    """긴 코드도 1900자씩 여러 코드 블록으로 분할."""
    blocks = []
    for chunk in chunk_text(content) or [""]:
        blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "language": _normalize_language(lang),
                "rich_text": [{"type": "text", "text": {"content": chunk}}],
            },
        })
    return blocks


# ------------------------------------------------------------
# 마크다운 표 → 노션 table 블록
# ------------------------------------------------------------

def _is_table_separator(line: str) -> bool:
    """| --- | :---: | 같은 정렬 구분 행인지 검사."""
    return bool(re.match(r"^\s*\|?\s*:?-{2,}.*\|", line)) and set(line) <= set("|-: \t")


def _parse_table_rows(lines: List[str]) -> List[List[str]]:
    """표 본문 줄들을 셀 배열로 파싱. 앞뒤 '|' 유무 모두 허용."""
    rows: List[List[str]] = []
    for line in lines:
        stripped = line.strip()
        # 양 끝의 불필요한 | 제거 후 셀 분할 (이스케이프된 \| 는 보존)
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        cells = [c.strip().replace("\\|", "|") for c in stripped.split("|")]
        rows.append(cells)
    return rows


def _table_block(row_lines: List[str]) -> Dict[str, Any]:
    """표 줄들(헤더+구분행+본문)을 노션 table 블록 1개로 변환."""
    raw_rows = _parse_table_rows(row_lines)

    # 두 번째 줄이 정렬 구분행이면 실제 데이터에서 제외
    has_sep = len(raw_rows) >= 2 and _is_table_separator(row_lines[1])
    data_rows = [raw_rows[0]] + (raw_rows[2:] if has_sep else raw_rows[1:])
    has_header = not has_sep  # 구분행이 있으면 첫 줄이 헤더라는 의미

    # 열 개수는 가장 많은 행 기준으로 맞추고, 부족한 셀은 빈 값으로 패딩
    width = max(len(r) for r in data_rows)

    children: List[Dict[str, Any]] = []
    for r in data_rows:
        padded = r + [""] * (width - len(r))
        cells = []
        for cell in padded[:width]:
            groups = _split_rich_text(parse_inline(cell))
            cells.append(groups[0] if groups else [])
        children.append({
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": cells},
        })

    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": children,
        },
    }


def _is_table_line(line: str) -> bool:
    """표 본문 줄인지 판단: | 로 시작하거나, 셀 구분 | 을 1개 이상 포함한 줄."""
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


# ------------------------------------------------------------
# 메인 파서: 마크다운 전체 → 블록 배열
# ------------------------------------------------------------

MAX_LIST_DEPTH = 2  # 블록 중첩 허용 단계 (리스트 항목 + children 1단계)


def markdown_to_notion_blocks(markdown: str) -> List[Dict[str, Any]]:
    """마크다운 문자열을 노션 블록 배열로 변환한다.

    리스트 중첩은 MAX_LIST_DEPTH 단계까지만 지원한다.
    (노션 API가 요청 1건당 그 이상의 children 중첩을 거부함)
    """
    if not markdown:
        return []

    markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
    lines = markdown.split("\n")

    blocks: List[Dict[str, Any]] = []
    paragraph: List[str] = []   # 일반 문단 줄 모음
    list_stack: List[tuple] = []  # (들여쓰기, 블록) — 중첩 리스트용
    in_code = False
    code_lines: List[str] = []
    code_lang = ""

    def flush_paragraph() -> None:
        nonlocal paragraph
        text = "\n".join(paragraph).strip()
        if text:
            blocks.extend(_rich_blocks("paragraph", text))
        paragraph = []

    def close_lists() -> None:
        nonlocal list_stack
        list_stack = []

    def make_list_item(kind: str, text: str, checked: Optional[bool]) -> Dict[str, Any]:
        """리스트 항목 블록 1개 생성."""
        if kind == "todo":
            btype = "to_do"
        elif kind == "numbered":
            btype = "numbered_list_item"
        else:
            btype = "bulleted_list_item"

        groups = _split_rich_text(parse_inline(text)) or [[]]
        body: Dict[str, Any] = {"rich_text": groups[0]}
        if kind == "todo":
            body["checked"] = bool(checked)
        return {"object": "block", "type": btype, btype: body}

    # 표 파싱에서 소비한 줄은 건너뛰기 위한 마커
    # (반복 중 리스트를 수정하지 않기 위해 인덱스 방식 사용)
    consumed_until = -1

    for line_index, line in enumerate(lines):
        stripped = line.strip()

        # 표로 이미 소비된 줄은 모든 처리에서 제외 (중복 출력 방지)
        if line_index <= consumed_until:
            continue

        # ===== 마크다운 표 (| 로 시작하는 연속된 줄) =====
        if not in_code and _is_table_line(line):
            flush_paragraph()
            close_lists()

            end = line_index
            while end < len(lines) and _is_table_line(lines[end]):
                end += 1

            blocks.append(_table_block(lines[line_index:end]))
            consumed_until = end - 1
            continue

        # ===== 코드 펜스 시작/끝 =====
        if stripped.startswith("```"):
            flush_paragraph()
            close_lists()
            if not in_code:
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            else:
                in_code = False
                blocks.extend(_code_blocks("\n".join(code_lines), code_lang))
            continue
        if in_code:
            code_lines.append(line)
            continue

        # ===== 빈 줄 =====
        if not stripped:
            flush_paragraph()
            close_lists()
            continue

        # ===== 구분선 --- *** ___ =====
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_paragraph()
            close_lists()
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue

        # ===== 제목 =====
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", stripped)
        if heading:
            flush_paragraph()
            close_lists()
            level = max(1, min(len(heading.group(1)), 3))  # 노션은 3단계까지
            blocks.extend(_rich_blocks(f"heading_{level}", heading.group(2)))
            continue

        # ===== 리스트 (체크박스 > 숫자 > 일반 순서로 검사) =====
        todo = re.match(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.+)$", line)
        numbered = re.match(r"^(\s*)(\d+)[.)]\s+(.+)$", line)
        bullet = re.match(r"^(\s*)[-*+]\s+(.+)$", line)

        if todo or numbered or bullet:
            flush_paragraph()
            if todo:
                indent, text = len(todo.group(1)), todo.group(3)
                checked = todo.group(2).lower() == "x"
                block = make_list_item("todo", text, checked)
            elif numbered:
                indent, text = len(numbered.group(1)), numbered.group(3)
                block = make_list_item("numbered", text, None)
            else:
                indent, text = len(bullet.group(1)), bullet.group(2)
                block = make_list_item("bullet", text, None)

            while list_stack and indent <= list_stack[-1][0]:
                list_stack.pop()

            if not list_stack:
                blocks.append(block)
                list_stack.append((indent, block))
            elif len(list_stack) >= MAX_LIST_DEPTH:
                # 노션 API는 요청 1건당 2단계 중첩(children 안의 children)까지만
                # 허용한다. 그보다 깊은 들여쓰기는 마지막 허용 단계에 평탄화하고
                # 시각적 위계만 남긴다. 스택에 쌓지 않으므로 이후 같은/더 깊은
                # 들여쓰기 항목도 계속 같은 부모로 평탄화된다.
                parent = list_stack[MAX_LIST_DEPTH - 1][1]
                ptype = parent["type"]
                ctype = block["type"]
                rt = block[ctype].setdefault("rich_text", [])
                rt.insert(0, {"type": "text", "text": {"content": "↳ "}})
                parent[ptype].setdefault("children", []).append(block)
            else:
                # 부모 리스트 항목의 children으로 중첩
                parent = list_stack[-1][1]
                ptype = parent["type"]
                parent[ptype].setdefault("children", []).append(block)
                list_stack.append((indent, block))
            continue

        # ===== 인용 =====
        quote = re.match(r"^\s*>\s?(.*)$", line)
        if quote:
            flush_paragraph()
            close_lists()
            blocks.extend(_rich_blocks("quote", quote.group(1)))
            continue

        # ===== 일반 문단 =====
        close_lists()
        paragraph.append(line)

    # 파일 끝 처리: 닫히지 않은 코드펜스 / 남은 문단
    if in_code:
        blocks.extend(_code_blocks("\n".join(code_lines), code_lang))
    else:
        flush_paragraph()

    return blocks


def split_into_batches(blocks: List[Dict[str, Any]], size: int = 80) -> List[List[Dict[str, Any]]]:
    """블록 배열을 API 요청 단위(size, 최대 100)로 분할."""
    return [blocks[i : i + size] for i in range(0, len(blocks), size)]
