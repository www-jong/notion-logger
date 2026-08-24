#!/usr/bin/env python3
"""
md2notion 변환 테스트 스크립트 — v0.4

하는 일:
    1. 샘플 마크다운(모든 지원 문법 포함)을 노션 블록으로 변환
    2. "[TEST] 마크다운 렌더링" 페이지를 만들고 본문에 업로드
       - 블록이 80개 넘어가면 여러 번 append (분할 업로드 검증 겸함)
    3. 페이지 URL 출력 → 노션에서 렌더링 직접 확인용

성공 판정 기준:
    - 제목/목록/코드블록/인용/구분선/굵게/기울임/링크가
      노션에서 의도대로 보임
    - 긴 코드블록(1900자 초과)도 잘림 없이 여러 블록으로 이어짐
"""

import sys

import requests

from notion_logger import config
from notion_logger.md2notion import markdown_to_notion_blocks, split_into_batches

# ------------------------------------------------------------
# 테스트용 샘플 마크다운 (지원 문법 전부 + 긴 코드블록)
# ------------------------------------------------------------

SAMPLE_MARKDOWN = """# 노션 로거 마크다운 테스트

이 문단은 **굵게**, *기울임*, ***둘 다***, `인라인 코드`,
~~취소선~~, [노션 링크](https://www.notion.so) 를 포함합니다.

## 목록 테스트

- 첫 번째 항목
- 두 번째 항목
  - 중첩된 항목 (들여쓰기)
    - 더 깊은 중첩
1. 숫자 목록 A
2. 숫자 목록 B

## 할 일

- [ ] 아직 안 한 일
- [x] 완료한 일

## 인용과 구분선

> 이것은 인용문입니다. **굵게**도 가능.

---

## 표 테스트

| 구분 | 내용 | 비고 |
| :--- | :--- | --- |
| 이름 | notion-logger | 에이전트 기록기 |
| 지원 | **굵게** 가능 | `코드`도 가능 |
| 정렬 | 좌측 | 우측 |

---

## 코드 블록 (python)

```python
def hello(name: str) -> str:
    \"\"\"인사 함수\"\"\"
    return f"Hello, {name}!"

print(hello("notion"))
```

## 긴 코드 블록 (1900자 초과 분할 확인)

```text
""" + ("A" * 60 + "\n") * 40 + """```

### 소제목 (h3)

끝. 위의 모든 요소가 정상적으로 보이면 성공.
"""


def create_page(page_title: str, blocks: list) -> str | None:
    """페이지 생성 + 첫 80개 블록 업로드. 성공 시 page id 반환."""
    res = requests.post(
        f"{config.NOTION_API_BASE}/pages",
        headers={
            "Authorization": f"Bearer {config.api_key()}",
            "Content-Type": "application/json",
            "Notion-Version": config.NOTION_VERSION,
        },
        json={
            "parent": {"database_id": config.database_id()},
            "properties": {
                "이름": {"title": [{"text": {"content": page_title}}]}
            },
            "children": blocks[:80],
        },
        timeout=30,
    )
    if res.status_code not in (200, 201):
        print(f"[오류] 페이지 생성 실패 ({res.status_code}): {res.text[:500]}")
        return None
    return res.json()["id"]


def append_blocks(page_id: str, blocks: list) -> bool:
    """남은 블록들을 80개씩 나눠 append."""
    for i, batch in enumerate(split_into_batches(blocks[80:]), start=2):
        res = requests.patch(
            f"{config.NOTION_API_BASE}/blocks/{page_id}/children",
            headers={
                "Authorization": f"Bearer {config.api_key()}",
                "Content-Type": "application/json",
                "Notion-Version": config.NOTION_VERSION,
            },
            json={"children": batch},
            timeout=30,
        )
        if res.status_code not in (200, 201):
            print(f"[오류] {i}번째 배치 실패 ({res.status_code}): {res.text[:500]}")
            return False
        print(f"  배치 {i} 업로드: {len(batch)}개 블록")
    return True


def main() -> None:
    config.load_env()

    if not config.is_configured():
        print("[오류] .env 설정 필요")
        sys.exit(1)

    blocks = markdown_to_notion_blocks(SAMPLE_MARKDOWN)
    print(f"변환 결과: 총 {len(blocks)}개 블록")

    page_id = create_page("[TEST] 마크다운 렌더링", blocks)
    if page_id is None:
        sys.exit(1)

    if len(blocks) > 80 and not append_blocks(page_id, blocks):
        sys.exit(1)

    url = f"https://www.notion.so/{page_id.replace('-', '')}"
    print("[성공] 마크다운 테스트 페이지 생성 완료")
    print(f"확인: {url}")


if __name__ == "__main__":
    main()
