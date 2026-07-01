"""Generic endpoint для отдачи markdown-файлов на UI-страницы /docs/:slug.

Whitelist slug → файл. Файлы смонтированы read-only в контейнер через
docker-compose (см. секцию `volumes` для backend).

Добавить новый doc:
  1. Положить .md в корень репо.
  2. Добавить mount `./X.md:/app/X.md:ro` в docker-compose.yml.
  3. Добавить запись в `_SLUG_TO_FILE`.
  4. На фронте дать ссылку на `/docs/<slug>`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from app.services.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/api/doc", tags=["doc-pages"])


_SLUG_TO_FILE: dict[str, str] = {
    "promo-calculator": "PROMO_CALCULATOR.md",
    "promo-calculator-wb": "PROMO_CALCULATOR_WB.md",
    "unit-plan": "UNIT_PLAN.md",
    # Менеджерские «как пользоваться» (user-facing, не методика).
    "unit-plan-guide": "UNIT_PLAN_GUIDE.md",
    "promo-margin-guide": "PROMO_MARGIN_GUIDE.md",
    # TASK-LEAD-095 — user-facing методички для /transit-calculator,
    # /supply-calculator, /pnl-reconciliation.
    "transit-calculator": "TRANSIT_CALCULATOR.md",
    "supply-calculator": "SUPPLY_CALCULATOR.md",
    "reconciliation": "RECONCILIATION.md",
}


def _candidate_paths(filename: str) -> list[Path]:
    return [
        Path(f"/app/{filename}"),
        Path(__file__).resolve().parents[3] / filename,
        Path(__file__).resolve().parents[2] / filename,
    ]


@router.get("/{slug}", response_class=PlainTextResponse)
async def get_doc(
    slug: str,
    _user: CurrentUser = Depends(get_current_user),
) -> str:
    """Вернуть содержимое markdown-документа по slug'у."""
    filename = _SLUG_TO_FILE.get(slug)
    if filename is None:
        raise HTTPException(404, f"doc slug {slug!r} not found")

    for path in _candidate_paths(filename):
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError as e:
                raise HTTPException(500, f"failed to read {filename}: {e}") from e

    raise HTTPException(
        404,
        f"{filename} not found on backend. Check docker-compose mount.",
    )
