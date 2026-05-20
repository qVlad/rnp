"""Endpoint для отдачи FEATURES.md фронту.

UI-страница `/features` фетчит этот текст и рендерит его как markdown.
Файл смонтирован в контейнер volume'ом `./FEATURES.md:/app/FEATURES.md:ro`
(см. docker-compose.yml). Изменения подхватываются без rebuild — read-only
mount читается при каждом запросе.

Доступ — любой авторизованный (не публичный, чтобы не сливать структуру
сервиса наружу). Tenant-неспецифичен.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/features-doc", tags=["features-doc"])

# Возможные пути к файлу. В docker — /app/FEATURES.md (mount), при локальном
# запуске backend'а вне docker — относительно репо.
_CANDIDATE_PATHS = [
    Path("/app/FEATURES.md"),
    Path(__file__).resolve().parents[3] / "FEATURES.md",  # repo_root/FEATURES.md
    Path(__file__).resolve().parents[2] / "FEATURES.md",
]


def _find_features_md() -> Path | None:
    for p in _CANDIDATE_PATHS:
        if p.is_file():
            return p
    return None


@router.get("", response_class=PlainTextResponse)
async def get_features_doc(_user: CurrentUser = Depends(get_current_user)) -> str:
    """Вернуть содержимое FEATURES.md как plain text."""
    path = _find_features_md()
    if path is None:
        raise HTTPException(
            404,
            "FEATURES.md not found on backend. Make sure docker-compose mounts "
            "./FEATURES.md to /app/FEATURES.md (read-only).",
        )
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"failed to read FEATURES.md: {e}") from e
