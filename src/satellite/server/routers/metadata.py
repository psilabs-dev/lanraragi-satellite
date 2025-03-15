"""
Metadata API

Various API for batch offline downloader metadata and metadata plugin invokation.
"""

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from satellite.server.auth import is_valid_api_key_header
from satellite.server.dependencies.common import LRRClientT, LoggerT
from satellite.server.dependencies.database import DatabaseServiceT
from satellite.server.dependencies.metadata import NhentaiArchivistMetadataServiceT, PixivUtilMetadataServiceT
from satellite.server.services.locks import LockStateT
from satellite.server.services.metadata import update_metadata, update_metadata_from_plugin

router = APIRouter(
    prefix="/api/metadata",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.post("/nhentai-archivist")
async def queue_update_data_from_nhentai_archivist(
    background_tasks: BackgroundTasks, metadata_service: NhentaiArchivistMetadataServiceT, lanraragi: LRRClientT,
    lock_state: LockStateT
):
    background_tasks.add_task(update_metadata, lanraragi, metadata_service, lock_state.RWLOCK)
    return JSONResponse({"message": "Queued metadata updates for nhentai archivist."})

@router.post("/pixivutil2")
async def queue_update_data_from_pixivutil2(
    background_tasks: BackgroundTasks, metadata_service: PixivUtilMetadataServiceT, lanraragi: LRRClientT, 
    lock_state: LockStateT
):
    background_tasks.add_task(update_metadata, lanraragi, metadata_service, lock_state.RWLOCK)
    return JSONResponse({"message": "Queued metadata updates for PixivUtil2."})

@router.post("/plugins/{plugin_namespace}")
async def queue_update_archive_metadata_with_plugin(
    lanraragi: LRRClientT, database: DatabaseServiceT, logger: LoggerT,
    background_tasks: BackgroundTasks, plugin_namespace: str, lock_state: LockStateT,
    retry_ok: bool=False, sleep_time: float=5
):
    """
    Creates a background task that gets all untagged archives, extracts metadata ID,
    invokes the metadata plugin call, and updates said archive with this metadata.
    
    To use this API, the corresponding credentials and cookies must be provided in the
    attached LANraragi server.

    If the metadata call does not exist (e.g. the post was deleted), this failure will 
    be recorded, so that the process will not try to repeat. This is many times more
    expensive than fetching from a local metadata database, but will may often fetch more
    accurate metadata.

    This will fetch all archives from LANraragi, and apply a PENDING status on them. It will
    then get the metadata ID from them via the GET metadata API, and invoke the metadata
    plugin API to get further metadata. This new metadata will be applied to the archive,
    as well as a OK status; if the metadata cannot be found, it will apply a NOT_FOUND
    status. This will continue until no PENDING archives are left. Archives with an OK
    status will not be used to invoke the metadata plugin on a second scan.

    However, if an Archive is NOT_FOUND, it may mean the Archive has been privated, deleted, 
    or otherwise unavailable. Such an Archive may be available for
    metadata fetching again. Therefore, after a certain period of time, we may invoke
    the metadata plugin on NOT_FOUND Archives. The rate at which this invokation takes
    place will be governed by ~exponential backoff equal to 2**(num_failures) days.

    Due to the rate-limiting nature of many data sources, this API call will be run synchronously and
    with backoff.

    Parameters
    ----------
    plugin_namespace : str
        Namespace of the metadata plugin to invoke (e.g., `pixivmetadata`, `nhplugin`)
    retry_ok : bool = False
        Retry metadata fetch for all successfully scanned archives.
    sleep_time : float = 5
        Sets an upper bound sleep time between metadata plugin calls (random.randint(0, 1) * sleep_time).
    """
    logger.info(f"[metadata_plugin] plugin namespace = {plugin_namespace}, max sleep time = {sleep_time}")
    if not plugin_namespace or plugin_namespace not in {"pixivmetadata", "nhplugin"}:
        return JSONResponse({
            "message": f"Misconfigured plugin namespace: {plugin_namespace}"
        }, status_code=400)
    background_tasks.add_task(
        update_metadata_from_plugin, lanraragi, database, plugin_namespace, lock_state.RWLOCK, sleep_time, retry_ok=retry_ok
    )
    return JSONResponse({
        "message": f"Queued invokation of the {plugin_namespace} metadata plugin."
    })
