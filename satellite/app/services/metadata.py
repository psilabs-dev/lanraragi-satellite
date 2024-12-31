from asyncio import Semaphore
import asyncio
import logging
import random
import time
from typing import Tuple

from aiohttp import ClientConnectionError
from aiorwlock import RWLock
from satellite.models import MetadataPluginTaskStatus
from satellite.service.database import DatabaseService
from satellite.service.metadata import MetadataService, NhentaiArchivistMetadataService, PixivUtil2MetadataService
from satellite.utils.lanraragi.client import LRRClient
from satellite.utils.lanraragi.tags import get_source_from_tags

logger = logging.getLogger("uvicorn.satellite")

async def update_metadata(lanraragi: LRRClient, metadata_service: MetadataService, lock: RWLock):
    if lock.writer.locked or lock.reader.locked:
        logger.warning("[update_metadata] Lock conflict, backing off.")
        return
    async with lock.writer_lock:
        start_time = time.time()
        untagged_archives = (await lanraragi.get_untagged_archives()).data
        if not untagged_archives:
            logger.info("[update_metadata] No untagged archives.")
            return
        logger.info(f"[update_metadata] Collected {len(untagged_archives)} untagged archives.")
        
        semaphore = Semaphore(value=8)
        async def __handle_archive_id(archive_id: str):
            async with semaphore:
                archive_metadata_response = await lanraragi.get_archive_metadata(archive_id)
                title = archive_metadata_response.title
                pixiv_id = metadata_service.get_id_from_title(title)
                metadata = await metadata_service.get_metadata_from_id(pixiv_id)
                retry_count = 0
                while True:
                    try:
                        response = await lanraragi.update_archive(
                            archive_id, title=metadata.title, tags=metadata.tags, summary=metadata.summary
                        )
                        logger.info(f"[update_metadata] metadata updated: {archive_id}")
                        return (archive_id, response.status_code)
                    except ClientConnectionError:
                        time_to_sleep = 2 ** (retry_count + 1)
                        await asyncio.sleep(time_to_sleep)
        tasks = [asyncio.create_task(__handle_archive_id(archive_id)) for archive_id in untagged_archives]
        await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        logger.info(f"[update_metadata] {len(tasks)} archives updated. Total time: {total_time}s.")

async def update_metadata_from_plugin(
        lanraragi: LRRClient, database: DatabaseService, namespace: str, lock: RWLock, avg_sleep_time: float, retry_ok: bool=False
):
    async def __handle_task(task: Tuple[str, str, int, float, int], task_i: int, total_tasks: int) -> int:
        """
        Handle a metadata plugin task. Returns 1 if metadata updated, else 0.
        """
        source = database.get_metadata_plugin_task_source(task)
        arcid = database.get_metadata_plugin_task_arcid(task)
        num_failures = database.get_metadata_plugin_task_num_failures(task)

        # first check if the archive exists in the server.
        archive_metadata = await lanraragi.get_archive_metadata(arcid)
        if not archive_metadata.success:
            await database.delete_metadata_plugin_task(arcid)
            logger.error(f"[metadata_plugin_{namespace}] Archive not found: {arcid}")
            return 0

        # invoke plugin: follow-up with sleep.
        plugin_response = await lanraragi.use_plugin(namespace, arcid, source)
        time_to_sleep = random.random() * avg_sleep_time # sleep with delay
        await asyncio.sleep(time_to_sleep)
        if plugin_response.success:
            data = plugin_response.data

            # collect and organize tags.
            current_tags: str = archive_metadata.tags
            current_tag_list = current_tags.strip().split(",") if current_tags else []
            new_tags: str = data.get("new_tags")
            new_tag_list = new_tags.strip().split(",") if new_tags else []
            # add current tags to list of new tags, only if they satisfy metadata-specific criteria.
            for current_tag in current_tag_list:
                if namespace == "pixivmetadata":
                    """
                    Under Pixiv, the following key-value tags must have unique keys for the artwork:

                    key                 behavior
                    artist              keep new    (artist name for the same pixiv ID may change over time)
                    date_uploaded       keep new    (since artist may private/unprivate artwork; date_created < date_uploaded)
                    date_created        keep new
                    """
                    if current_tag.startswith("artist:") and any(tag.startswith("artist:") for tag in new_tag_list):
                        continue
                    if current_tag.startswith("date_uploaded:") and any(tag.startswith("date_uploaded:") for tag in new_tag_list):
                        continue
                    if current_tag.startswith("date_created:") and any(tag.startswith("date_created:") for tag in new_tag_list):
                        continue

                new_tag_list.append(current_tag)
            tags = ",".join(new_tag_list)
            title: str = data.get("title")
            summary = data.get("summary")
            await lanraragi.update_archive(arcid, title=title, tags=tags, summary=summary)
            await database.update_metadata_plugin_task(arcid, source, namespace, MetadataPluginTaskStatus.OK.value, time.time(), 0)
            logger.info(f"[metadata_plugin_{namespace}] Task [{task_i + 1}/{total_tasks}] OK {source} - {title}")
            return 1
        else:
            # metadata probably does not exist; put this in NOT_FOUND.
            await database.update_metadata_plugin_task(arcid, source, namespace, MetadataPluginTaskStatus.NOT_FOUND.value, time.time(), num_failures + 1)
            logger.warning(f"[metadata_plugin_{namespace}] Task [{task_i + 1}/{total_tasks}] NOT_FOUND: {source}")
            return 0

    if lock.writer.locked or lock.reader.locked:
        logger.warning("[metadata_plugin] Already running task.")
        return
    async with lock.writer_lock:
        start_time = time.time()
        if namespace == "pixivmetadata":
            get_id_from_title = PixivUtil2MetadataService.get_id_from_title
            source_template = "https://www.pixiv.net/en/artworks/{id}"
        elif namespace == "nhplugin":
            get_id_from_title = NhentaiArchivistMetadataService.get_id_from_title
            source_template = "nhentai.net/g/{id}"
        else:
            logger.error(f"[metadata_plugin] Invalid or unsupported plugin namespace: {namespace}")
            return

        response = await lanraragi.get_all_archives()
        if response.status_code != 200:
            logger.error(f"[metadata_plugin_{namespace}] Failed to get archives (status {response.status_code}): ", str(response.error))
            return
        for archive in response.data:
            arcid = archive["arcid"]
            if await database.get_metadata_plugin_task_by_arcid(arcid):
                continue
            metadata_response = await lanraragi.get_archive_metadata(arcid)
            title: str = metadata_response.title
            tags: str = metadata_response.tags
            # get source from metadata if exists (by title or source tag)
            source: str
            if _source := get_source_from_tags(tags):
                source = _source
            elif _id := get_id_from_title(title):
                source = source_template.format(id=_id)
            else:
                logger.error(f"[metadata_plugin_{namespace}] ERROR No source found for arcid {arcid}.")
                await database.update_metadata_plugin_task(arcid, None, namespace, MetadataPluginTaskStatus.ERROR.value, time.time(), 0)
            # for remaining sources, add them to database with PENDING.
            await database.update_metadata_plugin_task(arcid, source, namespace, MetadataPluginTaskStatus.PENDING.value, time.time(), 0)
            logger.info(f"[metadata_plugin_{namespace}] PENDING: {arcid}")
        logger.info(f"[metadata_plugin_{namespace}] Completed inventory of metadata plugins.")

        num_metadata_updated = 0

        if retry_ok:
            # collect all OK tasks and re-fetch metadata for them.
            logger.info(f"[metadata_plugin_{namespace}] Start getting OK tasks...")
            ok_tasks = await database.get_metadata_plugin_task_by_status_and_namespace(MetadataPluginTaskStatus.OK.value, namespace)
            num_ok_tasks = len(ok_tasks)
            logger.info(f"[metadata_plugin_{namespace}] Retrieved {num_ok_tasks} OK tasks.")
            for i, task in enumerate(ok_tasks):
                num_metadata_updated += await __handle_task(task, i, num_ok_tasks)

        # now collect all PENDING tasks and fetch metadata for them.
        logger.info(f"[metadata_plugin_{namespace}] Start getting PENDING tasks...")
        pending_metadata_tasks = await database.get_metadata_plugin_task_by_status_and_namespace(MetadataPluginTaskStatus.PENDING.value, namespace)
        num_pending_tasks = len(pending_metadata_tasks)
        logger.info(f"[metadata_plugin_{namespace}] Retrieved {num_pending_tasks} PENDING tasks.")
        for i, pending_metadata_task in enumerate(pending_metadata_tasks):
            num_metadata_updated += await __handle_task(pending_metadata_task, i, num_pending_tasks)

        # now collect all NOT_FOUND tasks whose donotscan have expired and fetch metadata for them.
        logger.info(f"[metadata_plugin_{namespace}] Start getting NOT_FOUND tasks...")
        failed_metadata_tasks = await database.get_metadata_plugin_task_expired(time.time())
        num_failed_tasks = len(failed_metadata_tasks)
        logger.info(f"[metadata_plugin_{namespace}] Retrieved {num_failed_tasks} NOT_FOUND tasks.")
        for i, failed_task in enumerate(failed_metadata_tasks):
            num_metadata_updated += await __handle_task(failed_task, i, num_failed_tasks)
        
        total_time = time.time() - start_time
        logger.info(f"[metadata_plugin_{namespace}] Updated metadata for {num_metadata_updated} archives; Total time: {total_time}s.")