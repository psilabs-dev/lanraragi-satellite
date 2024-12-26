

from asyncio import Semaphore
import asyncio
import hashlib
import logging
from pathlib import Path

from satellite.models import ArchiveScanStatus
from satellite.service.database import DatabaseService
from satellite.utils.image import archive_contains_corrupted_image
from satellite.utils.scan import find_all_archives
logger = logging.getLogger("uvicorn.satellite")

async def scan_lrr_archives(contents_dir: Path, database: DatabaseService):
    logger.info(f"[scan_lrr_archives] run scan of {contents_dir}; this may take a while...")
    status = ArchiveScanStatus.PENDING.value

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
        await database.update_archive_scan(md5, path, status, mtime)
        archive_paths.append(path)
    logger.info(f"[scan_lrr_archives] found {len(all_archives)} archives; starting file analysis...")

    # phase 2: analyze each archive for corruption
    del archive_paths
    status = ArchiveScanStatus.PENDING.value
    rows = await database.get_archive_scans_by_status(status)
    logger.info(f"[scan_lrr_archives] collected {len(rows)} archives to analyze.")
    semaphore = Semaphore(value=8)
    async def __handle_row(row):
        _path = Path(DatabaseService.get_archive_scan_path(row))
        if not _path.exists():
            await database.delete_archive_scan(DatabaseService.get_archive_scan_md5(row))
        path = str(_path)
        md5 = DatabaseService.get_archive_scan_md5(row)
        mtime = DatabaseService.get_archive_scan_mtime(row)
        async with semaphore:
            try:
                if archive_contains_corrupted_image(_path):
                    logger.warning(f"[lrr_scan_archives] ANALYZE NOT OK: {_path.name}")
                    await database.update_archive_scan(md5, path, ArchiveScanStatus.CORRUPTED.value, mtime)
                else:
                    logger.info(   f"[lrr_scan_archives] ANALYZE OK:     {_path.name}")
                    await database.update_archive_scan(md5, path, ArchiveScanStatus.OK.value, mtime)
            except Exception:
                logger.error(      f"[lrr_scan_archives] ANALYZE ERROR: {_path.name}")
                await database.update_archive_scan(md5, path, ArchiveScanStatus.ERROR.value, mtime)
    tasks = [asyncio.create_task(__handle_row(row)) for row in rows]
    await asyncio.gather(*tasks)
    logger.info(f"[scan_lrr_archives] Scanned {len(tasks)} archives.")

async def delete_corrupted_archives(database: DatabaseService):
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