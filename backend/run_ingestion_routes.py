from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from admin_routes import verify_admin
from apify_run_ingestion import ingest_run

router = APIRouter(
    prefix="/api/admin",
    tags=["Run Ingestion"],
    dependencies=[Depends(verify_admin)],
)


class IngestRunRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=255)


def register_run_ingestion_routes(app, engine):

    @router.post("/ingest-run")
    def import_apify_run(data: IngestRunRequest):
        try:
            return ingest_run(engine, data.run_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc

    app.include_router(router)
