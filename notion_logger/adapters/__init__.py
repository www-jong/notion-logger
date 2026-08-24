"""어댑터 레지스트리: payload를 보고 알맞은 어댑터를 골라준다."""

from typing import Any, Dict, Optional

from .antigravity import AntigravityAdapter
from .base import Adapter

_ADAPTERS = [
    AntigravityAdapter(),
    # opencode 등 새 에이전트는 여기에 추가
]


def detect_adapter(payload: Any) -> Optional[Adapter]:
    """payload 형태를 보고 맞는 어댑터 반환. 못 찾으면 None."""
    for adapter in _ADAPTERS:
        if adapter.matches(payload):
            return adapter
    return None
