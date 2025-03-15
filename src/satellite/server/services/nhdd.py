import asyncio
import logging
import time

from satellite.service.nhdd import DeduplicationService


LOGGER = logging.getLogger("uvicorn.satellite")

async def create_page_embeddings(lock: asyncio.Lock, dd_service: DeduplicationService):
    LOGGER.info("Creating page embeddings.")
    start = time.time()
    try:
        async with lock:
            await dd_service.create_embedding_tasks()
            await dd_service.consume_pending_tasks()
        LOGGER.info(f"Completed page embedding job. Time: {time.time() - start}")
        return
    finally:
        await dd_service.close()

async def update_nhentai_archives_data(
        lock: asyncio.Lock, discover_archives: bool, fetch_favorites: bool, dd_service: DeduplicationService, redo_failed: bool
):
    LOGGER.info(f"Updating nhentai archives table. discover_archives = {discover_archives}, fetch_favorites = {fetch_favorites}.")
    start = time.time()
    try:
        async with lock:
            if discover_archives:
                await dd_service.update_nhentai_archives_table()
            if fetch_favorites:
                await dd_service.update_nhentai_favorites(redo_failed=redo_failed)
        LOGGER.info(f"Completed nhentai archive table job. Time: {time.time() - start}")
        return
    finally:
        await dd_service.close()

async def compute_subarchives(lock: asyncio.Lock, dd_service: DeduplicationService):
    LOGGER.info("Updating subarchives table. This may take a while...")
    start = time.time()
    try:
        async with lock:
            await dd_service.compute_subarchives()
        LOGGER.info(f"Completed subarchives job. Time: {time.time() - start}")
        return
    finally:
        await dd_service.close()

async def remove_duplicates(is_dry_run: bool, lock: asyncio.Lock, dd_service: DeduplicationService):
    LOGGER.info("Updating donotdelete file and removing duplicate archives from contents directory...")
    start = time.time()
    try:
        async with lock:
            results = await dd_service.remove_duplicate_archives_nhentai_archivist(is_dry_run=is_dry_run)
        LOGGER.info(f"Completed deduplication job. Time: {time.time() - start}s")
        return results
    finally:
        await dd_service.close()
