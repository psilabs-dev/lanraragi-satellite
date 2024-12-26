"""
Upload API

Ways to upload Archives and Archive-like folders to LANraragi from a folder, with
watching abilities.
"""

from asyncio import Semaphore
import logging
from pathlib import Path
from aiohttp import ClientConnectionError
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.app import config
from satellite.app.auth import is_valid_api_key_header
from satellite.app.services.upload import upload_archives_from_folder
from satellite.service.database import DatabaseService
from satellite.utils.lanraragi.client import LRRClient

logger = logging.getLogger("uvicorn.satellite")
router = APIRouter(
    prefix="/api/upload",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.post("")
async def queue_upload_archives(background_tasks: BackgroundTasks, archive_is_dir: bool=False, semaphore_val: int=8):
    """
    Creates a background task to upload all Archives from a designated upload 
    directory configured by the environment variable `UPLOAD_DIR`.

    This process requires only read access to the contents of the upload directory, 
    and API access to the target LANraragi server.

    Parameters
    ----------
    archive_is_dir : bool = False
        When False, scans for archives that are readily processed by LANraragi, e.g.
        ".cbz", ".zip" files. When set to True, scans for folders which contain images
        and no subfolders. This setting is for artworks downloaded by PixivUtil2.
    """

    # get required configurations
    lrr_host = config.satellite_config.LRR_HOST
    lrr_api_key = config.satellite_config.LRR_API_KEY
    upload_dir = config.satellite_config.UPLOAD_DIR
    db_path = config.satellite_config.SATELLITE_DB_PATH

    if not lrr_host:
        return JSONResponse({
            "message": "LRR_HOST not configured!"
        }, status_code=500)
    if not lrr_api_key:
        return JSONResponse({
            "message": "LRR_API_KEY not configured!"
        }, status_code=500)
    if not upload_dir:
        return JSONResponse({
            "message": "UPLOAD_DIR not configured!"
        }, status_code=500)
    if not db_path:
        return JSONResponse({
            "message": "SATELLITE_DB_PATH not configured!"
        }, status_code=500)

    # check if LANraragi connection is available
    lanraragi = LRRClient(lrr_host=lrr_host, lrr_api_key=lrr_api_key)
    try:
        response = await lanraragi.get_shinobu_status()
        if response.status_code != 200:
            return JSONResponse({
                "message": "API authentication failed: " + response.message
            }, status_code=response.status_code)
    except ClientConnectionError as client_connection_err:
        return JSONResponse({
            "message": "Failed to reach LANraragi server: " + str(client_connection_err)
        }, status_code=404)

    # validate upload directory
    upload_dir = Path(upload_dir)
    if not upload_dir.exists():
        return JSONResponse({
            "message": "UPLOAD_DIR folder not configured: " + upload_dir
        }, status_code=500)
    if not upload_dir.is_dir():
        return JSONResponse({
            "message": "UPLOAD_DIR is not directory: " + upload_dir
        }, status_code=500)
    
    # validate database
    db_path = Path(db_path)
    if not db_path.exists():
        return JSONResponse({
            "message": "SATELLITE_DB_PATH not found: " + db_path
        }, status_code=500)
    if not db_path.is_file():
        return JSONResponse({
            "message": "SATELLITE_DB_PATH is not a file: " + db_path
        }, status_code=500)
    database = DatabaseService(db_path)

    semaphore = Semaphore(value=semaphore_val)
    background_tasks.add_task(
        upload_archives_from_folder, lanraragi, database, upload_dir, semaphore, archive_is_dir=archive_is_dir
    )

    # perform archives upload job
    return JSONResponse({
        "message": "Queued archive upload job.."
    })
