import asyncio
from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.server.auth import is_valid_api_key_header
from satellite.server.dependencies.nhdd.database import NhddDatabaseServiceT
from satellite.server.dependencies.nhdd.deduplication import DeduplicationServiceT
from satellite.server.services.locks import LockStateT
from satellite.server.services.nhdd import compute_subarchives, create_page_embeddings, remove_duplicates, update_nhentai_archives_data
from satellite.service.nhdd import ArchiveEmbeddingJobStatus, MetadataPluginStatus

nhdd_router = APIRouter(
    prefix="/api/nhdd",
    dependencies=[Depends(is_valid_api_key_header)]
)

@nhdd_router.get("/duplicates")
async def get_duplicate_archives(dd_service: DeduplicationServiceT):
    """
    Get all archives which are duplicates (lesser-duplicate or equal-duplicate).
    """
    duplicates = await dd_service.get_duplicate_archives()
    return JSONResponse({
        "message": "success",
        "duplicates": duplicates
    })

@nhdd_router.get("/duplicates/{archive_id}")
async def get_is_duplicate(archive_id: str, dd_service: DeduplicationServiceT):
    """
    TODO: Get subarchive info on archive by ID. Returns whether it is a duplicate, and
    what archive it is a duplicate of.
    """
    return JSONResponse({
        "message": "Success",
        "is_duplicate": True,
        "is_duplicate_of": "xxx"
    })

@nhdd_router.delete("/duplicates")
async def delete_duplicate_archives(dd_service: DeduplicationServiceT, background_tasks: BackgroundTasks, lock_state: LockStateT, is_dry_run: bool=False):
    """
    Delete duplicate archives from the local filesystem. To do this, perform file discovery and
    match archive ID to filepath.

    Other option: make API call to delete archives from the LRR server.
    """
    results = await remove_duplicates(is_dry_run, lock_state.contents_lock, dd_service)
    return JSONResponse({
        "message": "OK",
        "deleted": results.deleted_duplicates,
        "deleted-size": results.duplicate_size,
        "failed": results.delete_failed,
        "all": results.lrr_contents_size
    })

@nhdd_router.get("/page-embeddings/status")
async def get_create_page_embeddings_status(db: NhddDatabaseServiceT):
    num_success, num_failed, num_pending, num_notfound, num_skipped = await asyncio.gather(*[
        asyncio.create_task(db.get_num_archive_embedding_jobs_by_status(status)) for status in [
            ArchiveEmbeddingJobStatus.SUCCESS, 
            ArchiveEmbeddingJobStatus.FAILED,
            ArchiveEmbeddingJobStatus.PENDING, 
            ArchiveEmbeddingJobStatus.NOT_FOUND, 
            ArchiveEmbeddingJobStatus.SKIPPED
        ]
    ])
    return JSONResponse({
        "success": num_success,
        "failed": num_failed,
        "pending": num_pending,
        "not_found": num_notfound,
        "skipped": num_skipped
    })

@nhdd_router.post("/page-embeddings")
async def queue_create_page_embeddings(background_tasks: BackgroundTasks, dd_service: DeduplicationServiceT, lock_state: LockStateT):
    """
    Queue a job to create embeddings out of every page of every archive in the LANraragi server.
    Only one job can (and should) run at a time.
    """
    lock = lock_state.create_page_embeddings_lock
    if lock.locked():
        return JSONResponse({
            "message": "A create page embedding job is already queued."
        }, status_code=423)
    background_tasks.add_task(create_page_embeddings, lock, dd_service)
    return JSONResponse({
        "message": "Queued create page embeddings."
    })

@nhdd_router.get("/nhentai-archives/favorites/status")
async def get_nhentai_archives_favorites_job_task_status(db: NhddDatabaseServiceT):
    num_success, num_failed, num_pending, num_notfound = await asyncio.gather(*[
        asyncio.create_task(db.get_num_archive_metadata_jobs_by_status(status)) for status in [
            MetadataPluginStatus.SUCCESS, MetadataPluginStatus.FAILED, MetadataPluginStatus.PENDING, MetadataPluginStatus.NOT_FOUND
        ]
    ])
    return JSONResponse({
        "success": num_success,
        "failed": num_failed,
        "pending": num_pending,
        "not_found": num_notfound
    })

@nhdd_router.post("/nhentai-archives")
async def queue_nhentai_archives_update(
    background_tasks: BackgroundTasks, dd_service: DeduplicationServiceT, lock_state: LockStateT,
    discover_archives: bool=True, fetch_favorites: bool=False, redo_failed: bool=False
):
    """
    Queue a job to discover archives from the LRR server and put them to a database.
    Also, add a long-running job to fetch the favorites count for all nhentai archives.

    parameters
    ----------
    discover_archives : True
        Get all archives from the LRR server and push them to postgres.
    
    fetch_favorites : False
        Uses the LRR nhentai plugin to fetch the favorites count for all nhentai archives.
        By default the favorites count for all archives is -1.
    
    redo_failed : False
        Fetch metadata for archives whose task execution has previously failed.
    """
    lock = lock_state.nhentai_archives_data_lock
    if lock.locked():
        return JSONResponse({
            "message": "A nhentai table update job is already queued."
        }, status_code=423)
    background_tasks.add_task(update_nhentai_archives_data, lock, discover_archives, fetch_favorites, dd_service, redo_failed)
    return JSONResponse({
        "message": "Queued nhentai table updates."
    })

@nhdd_router.post("/subarchives")
async def queue_compute_subarchives(
    background_tasks: BackgroundTasks, dd_service: DeduplicationServiceT, lock_state: LockStateT
):
    """
    Queue a job to discover duplicates from all nhentai archives discovered in the
    database.
    """
    lock = lock_state.compute_subarchives_lock
    if lock.locked():
        return JSONResponse({
            "message": "A subarchive computation job is already queued."
        }, status_code=423)
    background_tasks.add_task(compute_subarchives, lock, dd_service)
    return JSONResponse({
        "message": "Queued subarchive computation."
    })

@nhdd_router.delete("/db/archive_embedding_job")
async def delete_archive_embedding_job_table(db: NhddDatabaseServiceT):
    await db.clear_archive_embedding_job_table()
    return JSONResponse({
        "message": "Table deleted: archive_embedding_job"
    })

@nhdd_router.delete("/db/page")
async def delete_page_table(db: NhddDatabaseServiceT):
    await db.clear_page_table()
    return JSONResponse({
        "message": "Table deleted: page"
    })

@nhdd_router.delete("/db/subarchive_map")
async def delete_subarchive_map_table(db: NhddDatabaseServiceT):
    await db.clear_subarchive_map_table()
    return JSONResponse({
        "message": "Table deleted: subarchive_map"
    })

@nhdd_router.delete("/db/archive_metadata_job")
async def delete_archive_metadata_job_table(db: NhddDatabaseServiceT):
    await db.clear_archive_metadata_job_table()
    return JSONResponse({
        "message": "Table deleted: archive_metadata_job"
    })

@nhdd_router.delete("/db/nhentai_archive")
async def delete_nhentai_archive_table(db: NhddDatabaseServiceT):
    await db.clear_nhentai_archive_table()
    return JSONResponse({
        "message": "Table deleted: nhentai_archive"
    })