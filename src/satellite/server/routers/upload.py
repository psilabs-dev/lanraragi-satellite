"""
Upload API

Ways to upload Archives and Archive-like folders to LANraragi from a folder, with
watching abilities.
"""

from asyncio import Semaphore
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.server.auth import is_valid_api_key_header
from satellite.server.dependencies.common import ConfigT, LRRClientT, LoggerT
from satellite.server.dependencies.database import DatabaseServiceT
from satellite.server.services.locks import LockStateT
from satellite.server.services.upload import upload_archives_from_folder

router = APIRouter(
    prefix="/api/upload",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.post("")
async def queue_upload_archives(
    config: ConfigT, lanraragi: LRRClientT, lock_state: LockStateT, database: DatabaseServiceT, logger: LoggerT,
    background_tasks: BackgroundTasks, archive_is_dir: bool=False, semaphore_val: int=8
):
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
    logger.info(f"[upload_archives] uploading folder-like archives = {archive_is_dir}, semaphore value = {semaphore_val}")

    # get required configurations
    upload_dir = config.UPLOAD_DIR
    db_path = config.SATELLITE_DB_PATH

    if not upload_dir:
        return JSONResponse({
            "message": "UPLOAD_DIR not configured!"
        }, status_code=500)
    if not db_path:
        return JSONResponse({
            "message": "SATELLITE_DB_PATH not configured!"
        }, status_code=500)

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

    semaphore = Semaphore(value=semaphore_val)
    background_tasks.add_task(
        upload_archives_from_folder, lanraragi, database, upload_dir, semaphore, lock_state.RWLOCK, archive_is_dir=archive_is_dir
    )

    # perform archives upload job
    return JSONResponse({
        "message": "Queued archive upload job.."
    })
