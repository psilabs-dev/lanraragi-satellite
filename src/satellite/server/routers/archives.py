"""
Archives API

Provides a way to do Archive processing tasks. The primary task of interest is the scanning and removal of
Archives that contain corrupted images from the LANraragi contents directory.

To use this API, the server must at least have RW access to the contents directory.
"""

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.server.auth import is_valid_api_key_header
from satellite.server.dependencies.common import ConfigT, LoggerT
from satellite.server.dependencies.database import DatabaseServiceT
from satellite.server.services.locks import LockStateT
from satellite.server.services.archives import delete_corrupted_archives, scan_lrr_archives

router = APIRouter(
    prefix="/api/archives",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.post("/scan")
async def queue_scan_lrr_archives(
    background_tasks: BackgroundTasks, database: DatabaseServiceT, lock_state: LockStateT, config: ConfigT, logger: LoggerT,
    num_workers: int=0, batch_size: int=1000
):
    """
    Queue a background task to scan all archives in the LRR contents directory for corrupted archives,
    and save scan status to the server database for future processing.

    parameters
    ----------
    num_workers : 0
        Number of workers/processes to analyze archives. Must be non-negative. Cannot exceed number of CPUs detected. If
        number of workers = 1, defaults to running a single-process background task. If number of workers = 0, uses
        number equal to the number of CPU cores.
    
    batch_size : 1000
        When multiprocessing, set the size of an archive batch to analyze before saving results to a database.
        Higher batch size leads to greater performance, while lower batch size saves progress is more reliable against
        unexpected interruptions.
    """
    if num_workers == 0:
        logger.info(f"[lrr_scan_archives] Received request: using all cpus, batch = {batch_size}")
    else:
        logger.info(f"[lrr_scan_archives] Received request: cpus = {num_workers}, batch = {batch_size}")
    contents_dir = config.LRR_CONTENTS_DIR
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
    try:
        num_workers = int(num_workers)
        if num_workers < 0:
            raise ValueError
    except ValueError:
        return JSONResponse({
            "message": f"Invalid number of workers: {num_workers} must be non-negative integer."
        }, status_code=400)
    background_tasks.add_task(scan_lrr_archives, contents_dir, database, num_workers, batch_size, lock_state.RWLOCK)
    return JSONResponse({"message": f"Queued file scan of {contents_dir}."})

@router.get("")
async def get_lrr_archives(status: int, database: DatabaseServiceT, logger: LoggerT, limit: int=100_000):
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
    results = await database.get_archive_scans_by_status(status)
    return JSONResponse(results)

@router.delete("/corrupted")
async def queue_delete_corrupted_archives(
    background_tasks: BackgroundTasks, lock_state: LockStateT, database: DatabaseServiceT, logger: LoggerT
):
    """
    Run background job to delete all corrupted archives.
    """
    background_tasks.add_task(delete_corrupted_archives, database, lock_state.RWLOCK)
    return JSONResponse({"message": "Queued deletion of corrupted archives."})
