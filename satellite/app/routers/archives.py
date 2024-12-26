"""
Archives API

Provides a way to do Archive processing tasks. The primary task of interest is the scanning and removal of
Archives that contain corrupted images from the LANraragi contents directory.

To use this API, the server must at least have RW access to the contents directory.
"""

import logging
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.app import config
from satellite.app.auth import is_valid_api_key_header
from satellite.app.services.archives import delete_corrupted_archives, scan_lrr_archives
from satellite.service.database import DatabaseService

logger = logging.getLogger("uvicorn.satellite")
router = APIRouter(
    prefix="/api/archives",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.post("/scan")
async def queue_scan_lrr_archives(background_tasks: BackgroundTasks):
    """
    Queue a background task to scan all archives in the LRR contents directory for corrupted archives,
    and save scan status to the server database for future processing.
    """
    contents_dir = config.satellite_config.LRR_CONTENTS_DIR
    if not contents_dir:
        return JSONResponse({"message": "LRR contents not configured!"}, status_code=404)
    if not contents_dir.exists():
        return JSONResponse({
            "message": f"LRR contents not found! {contents_dir}"
        }, status_code=404)
    if not contents_dir.is_dir():
        return JSONResponse({
            "message": f"LRR contents is not a directory: {contents_dir}"
        }, status_code=500)
    db = config.satellite_config.SATELLITE_DB_PATH
    if not db.exists():
        return JSONResponse({"message": "No database!"}, status_code=404)
    database = DatabaseService(db)
    background_tasks.add_task(scan_lrr_archives, contents_dir, database)
    return JSONResponse({"message": f"Queued file scan of {contents_dir}."})

@router.get("")
async def get_lrr_archives(status: int, limit: int=100_000):
    """
    Get archives by scan status.

    | status no | status |
    | - | - |
    | 0 | OK |
    | 1 | CORRUPTED |
    | 2 | PENDING |
    | 3 | DO_NOT_SCAN |
    | 4 | ERROR |
    """
    db = config.satellite_config.SATELLITE_DB_PATH
    if not db.exists():
        return JSONResponse({"message": "No database!"}, status_code=404)
    database = DatabaseService(db)
    results = await database.get_archive_scans_by_status(status)
    return JSONResponse(results)

@router.delete("/corrupted")
async def queue_delete_corrupted_archives(background_tasks: BackgroundTasks):
    """
    Run background job to delete all corrupted archives.
    """
    db = config.satellite_config.SATELLITE_DB_PATH
    if not db.exists():
        return JSONResponse({"message": "No database!"}, status_code=404)
    database = DatabaseService(db)
    background_tasks.add_task(delete_corrupted_archives, database)
    return JSONResponse({"message": "Queued deletion of corrupted archives."})
