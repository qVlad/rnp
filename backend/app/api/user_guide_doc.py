"""Endpoint для отдачи USER_GUIDE.md фронту (TASK-LEAD-075).

User-facing версия каталога функций — описания фич бизнес-языком, без
путей в коде / API / SQL. Рендерится на странице `/features` при выборе
закладки «Для пользователя» (toggle в UI).

Файл смонтирован в контейнер volume'ом `./USER_GUIDE.md:/app/USER_GUIDE.md:ro`
(см. docker-compose.yml). Изменения подхватываются без rebuild.

Доступ — любой авторизованный.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/user-guide-doc", tags=["user-guide-doc"])

_CANDIDATE_PATHS = [
    Path("/app/USER_GUIDE.md"),
    Path(__file__).resolve().parents[3] / "USER_GUIDE.md",
    Path(__file__).resolve().parents[2] / "USER_GUIDE.md",
]


def _find_user_guide() -> Path | None:
    for p in _CANDIDATE_PATHS:
        if p.is_file():
            return p
    return None


@router.get("", response_class=PlainTextResponse)
async def get_user_guide_doc(_user: CurrentUser = Depends(get_current_user)) -> str:
    """Вернуть содержимое USER_GUIDE.md как plain text."""
    path = _find_user_guide()
    if path is None:
        raise HTTPException(
            404,
            "USER_GUIDE.md not found on backend. Make sure docker-compose mounts "
            "./USER_GUIDE.md to /app/USER_GUIDE.md (read-only).",
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"failed to read USER_GUIDE.md: {e}") from e
