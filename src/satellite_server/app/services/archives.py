

from asyncio import Semaphore
import asyncio
from concurrent.futures import ProcessPoolExecutor
import enum
from functools import partial
import hashlib
import logging
import multiprocessing
from pathlib import Path
import time
from typing import Tuple

from aiorwlock import RWLock

from satellite_server.models import ArchiveScanStatus
from satellite_server.service.database import DatabaseService
from satellite_server.utils.image import archive_contains_corrupted_image
from satellite_server.utils.scan import find_all_archives
logger = logging.getLogger("uvicorn.satellite")

class ArchiveAnalysisResponse(enum.Enum):
    ARCHIVE_OK = 1
    ARCHIVE_NOT_OK = 2
    ERROR = 3

def __analyze_archive(path_str: str) -> ArchiveAnalysisResponse:
    """
    CPU-bound archive analysis function.
    """
    _path = Path(path_str)
    try:
        if archive_contains_corrupted_image(_path):
            return ArchiveAnalysisResponse.ARCHIVE_NOT_OK
        return ArchiveAnalysisResponse.ARCHIVE_OK
    except Exception:
        return ArchiveAnalysisResponse.ERROR

async def scan_lrr_archives(contents_dir: Path, database: DatabaseService, num_workers: int, batch_size: int, lock: RWLock):

    async def __handle_response(md5: str, path_name: str, response: ArchiveAnalysisResponse, mtime: float, row_id: int, num_rows: int):
        """
        Process and log response.
        """
        if response == ArchiveAnalysisResponse.ARCHIVE_NOT_OK:
            logger.warning(
                f"[lrr_scan_archives] ANALYZE NOT OK [{row_id+1}/{num_rows}]: {path_name}"
            )
            await database.update_archive_scan(md5, path_name, ArchiveScanStatus.CORRUPTED.value, mtime)
        elif response == ArchiveAnalysisResponse.ARCHIVE_OK:
            logger.info(
                f"[lrr_scan_archives] ANALYZE OK     [{row_id+1}/{num_rows}]: {path_name}"
            )
            await database.update_archive_scan(md5, path_name, ArchiveScanStatus.OK.value, mtime)
        else:
            logger.error(
                    f"[lrr_scan_archives] ANALYZE ERROR  [{row_id+1}/{num_rows}]: {path_name}"
            )
            await database.update_archive_scan(md5, path_name, ArchiveScanStatus.ERROR.value, mtime)

    async def __handle_row(row: Tuple[str, str, int, float], row_id: int, num_rows: int, semaphore: asyncio.Semaphore):
        _path = Path(DatabaseService.get_archive_scan_path(row))
        if not _path.exists():
            await database.delete_archive_scan(DatabaseService.get_archive_scan_md5(row))
        md5 = DatabaseService.get_archive_scan_md5(row)
        mtime = DatabaseService.get_archive_scan_mtime(row)
        async with semaphore:
            response = __analyze_archive(_path)
            await __handle_response(md5, _path.name, response, mtime, row_id, num_rows)

    # check and adjust number of workers.
    is_multi_process = False
    cpu_count = multiprocessing.cpu_count()
    if num_workers == 0:
        logger.info("[scan_lrr_archives] Using all available cpus.")
        is_multi_process = True
        num_workers = cpu_count
    elif num_workers > 1:
        is_multi_process = True
        if num_workers > cpu_count:
            logger.info(f"[scan_lrr_archives] Number of workers {num_workers} exceeds cpu count {cpu_count}, reducing.")
            num_workers = cpu_count

    logger.info(f"[scan_lrr_archives] run scan of {contents_dir}; this may take a while...")
    if lock.writer.locked:
        logger.warning("[scan_lrr_archives] Lock conflict, backing off.")
        return
    async with lock.reader_lock:
        start_time = time.time()

        # phase 1: scan all archives
        all_archives = find_all_archives(contents_dir)
        archive_paths = []
        for archive in all_archives:
            path = str(archive.absolute())
            mtime = archive.stat().st_mtime
            md5 = hashlib.md5(path.encode('utf-8')).hexdigest()
            row = await database.get_archive_scan_by_md5(md5)
            if row and DatabaseService.get_archive_scan_mtime(row) == mtime: # archive is scanned and has result.
                continue
            await database.update_archive_scan(md5, path, ArchiveScanStatus.PENDING.value, mtime)
            archive_paths.append(path)
        logger.info(f"[scan_lrr_archives] found {len(all_archives)} archives; starting file analysis...")

        # phase 2: analyze each archive for corruption
        del archive_paths
        rows = await database.get_archive_scans_by_status(ArchiveScanStatus.PENDING.value)
        logger.info(f"[scan_lrr_archives] collected {len(rows)} archives to analyze.")
        semaphore = Semaphore(value=8)

        num_rows = len(rows)

        if is_multi_process:
            loop = asyncio.get_running_loop()
            chunk_count = (num_rows + batch_size - 1) // batch_size
            
            with ProcessPoolExecutor(max_workers=num_workers) as executor:

                for chunk_idx in range(chunk_count):
                    start = chunk_idx * batch_size
                    end = min(start + batch_size, num_rows)
                    chunk = rows[start:end]

                    tasks = []
                    for offset, row in enumerate(chunk):
                        row_id = start + offset
                        path_str = DatabaseService.get_archive_scan_path(row)
                        md5 = DatabaseService.get_archive_scan_md5(row)
                        mtime = DatabaseService.get_archive_scan_mtime(row)
                        future = loop.run_in_executor(executor, partial(__analyze_archive, path_str))
                        tasks.append((future, row_id, row, md5, path_str, mtime))
                    for future, row_id, row, md5, path_str, mtime in tasks:
                        try:
                            response: ArchiveAnalysisResponse = await future
                        except Exception as e:
                            logger.error(
                                f"[lrr_scan_archives] ANALYZE ERROR  [{row_id+1}/{num_rows}]: {Path(path_str).name}, ex={e}"
                            )
                            await database.update_archive_scan(md5, path_str, ArchiveScanStatus.ERROR.value, mtime)
                            continue
                        path = Path(path_str)
                        if not path.exists():
                            await database.delete_archive_scan(md5)
                            continue
                        await __handle_response(md5, path.name, response, mtime, row_id, num_rows)
                    logger.info(f"[lrr_scan_archives] Finished chunk [{chunk_idx+1}/{chunk_count}]")
        else:
            tasks = [asyncio.create_task(__handle_row(row, row_id, num_rows, semaphore)) for row_id, row in enumerate(rows)]
            await asyncio.gather(*tasks)

        total_time = time.time() - start_time
        logger.info(f"[scan_lrr_archives] Scanned {num_rows} archives. Total time: {total_time}s.")

async def delete_corrupted_archives(database: DatabaseService, lock: RWLock):
    if lock.reader.locked and lock.writer.locked:
        logger.warning("[delete_corrupted_archives] Lock conflict; backing off.")
        return
    async with lock.writer_lock:
        start_time = time.time()
        status = ArchiveScanStatus.CORRUPTED.value
        rows = await database.get_archive_scans_by_status(status)
        num_deleted = 0
        for row in rows:
            try:
                _path = Path(DatabaseService.get_archive_scan_path(row))
                _path.unlink()
                num_deleted += 1
                logger.info(f"[delete_corrupted_archives] DELETE: {_path}")
            except FileNotFoundError:
                continue
            await database.delete_archive_scan(row[0])
        total_time = time.time() - start_time
        logger.info(f"[delete_corrupted_archives] Deleted {num_deleted} archives. Total time: {total_time}s.")
