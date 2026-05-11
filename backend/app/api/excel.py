"""Excel import/export router for reference-data tables.

Endpoints:
- GET  /api/excel/entities          — list of supported entities + columns
- GET  /api/excel/{entity}/export   — download .xlsx with all rows
- POST /api/excel/{entity}/import   — upload .xlsx, returns counts + errors
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.auth import get_db_tenant_scoped
from app.services import excel_io

router = APIRouter(prefix="/api/excel", tags=["excel"])

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/entities")
async def list_entities() -> dict[str, list[dict[str, object]]]:
    return {
        "items": [
            {
                "name": name,
                "label": excel_io.ENTITY_LABELS.get(name, name),
                "columns": excel_io.SCHEMAS[name],
            }
            for name in excel_io.SCHEMAS
        ]
    }


@router.get("/{entity}/export")
async def export_entity(
    entity: str, session: AsyncSession = Depends(get_db_tenant_scoped)
) -> Response:
    try:
        data = await excel_io.export_excel(session, entity=entity)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return Response(
        content=data,
        media_type=XLSX_MIME,
        headers={"Content-Disposition": f'attachment; filename="rnp_{entity}.xlsx"'},
    )


@router.post("/{entity}/import")
async def import_entity(
    entity: str,
    file: UploadFile,
    session: AsyncSession = Depends(get_db_tenant_scoped),
) -> dict[str, object]:
    if entity not in excel_io.SCHEMAS:
        raise HTTPException(404, f"unknown entity: {entity}")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty file")
    try:
        return await excel_io.import_excel(session, entity=entity, file_bytes=raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"import failed: {e}") from e
