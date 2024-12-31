
from asyncio import Semaphore
import asyncio
import hashlib
import logging
from pathlib import Path
import tempfile
import time

from aiohttp import ClientConnectionError
from aiorwlock import RWLock

from satellite.service.database import DatabaseService
from satellite.utils.file import flat_folder_to_zip
from satellite.utils.lanraragi.client import LRRClient
from satellite.utils.lanraragi.upload import compute_upload_checksum
from satellite.utils.lanraragi.validation import get_signature_hex, is_valid_signature_hex
from satellite.utils.scan import find_all_archives, find_all_leaf_folders


logger = logging.getLogger("uvicorn.satellite")

async def upload_archives_from_folder(
        lanraragi: LRRClient, database: DatabaseService, upload_dir: Path, semaphore: Semaphore, lock: RWLock,
        archive_is_dir: bool=False
):    
    async def __handle_archive(archive: Path) -> int:
        async with semaphore:
            archive = archive.absolute()
            file_name = archive.name
            path = str(archive)
            md5 = hashlib.md5(path.encode('utf-8')).hexdigest()
            mtime = archive.stat().st_mtime

            # check cache
            row = await database.get_archive_upload_by_md5(md5)
            if row and DatabaseService.get_archive_upload_mtime(row) == mtime:
                logger.debug(f"[upload_archives] DUPLICATE: {file_name}")
                return 0
            
            if not archive_is_dir and not is_valid_signature_hex(get_signature_hex(archive)):
                logger.info(f"[upload_archives] INVALID SIGNATURE: {file_name}")
                return 0
            
            async def __do_upload(_archive: Path, _file_name: str):
                with open(_archive, 'rb') as br:
                    checksum = compute_upload_checksum(br)
                    br.seek(0)
                    checksum_mismatch_retries = 0
                    connection_retries = 0
                    while True:
                        try:
                            response = await lanraragi.upload_archive(
                                br,
                                _file_name,
                                archive_checksum=checksum,
                            )
                            status_code = response.status_code
                            if status_code == 200:
                                await database.update_archive_upload(md5, path, mtime)
                                logger.info(f"[upload_archives] UPLOAD: {_file_name}")
                                return 1
                            elif status_code == 409: # archive exists in server.
                                logger.info(f"[upload_archives] DUPLICATE ONLINE: {_file_name}")
                                await database.update_archive_upload(md5, path, mtime)
                                return 0
                            elif status_code == 417: # try again for checksum mismatch
                                if checksum_mismatch_retries < 3:
                                    checksum_mismatch_retries += 1
                                    continue
                                else:
                                    logger.error(f"[upload_archives] CHECKSUM MISMATCH: {_file_name}")
                                    return 0
                            else:
                                logger.error(f"[upload_archives] Failed to upload {_file_name} ({status_code}): {response.error}")
                                return 0
                        except ClientConnectionError:
                            time_to_sleep = 2 ** (connection_retries + 1)
                            await asyncio.sleep(time_to_sleep)
            if archive_is_dir:
                with tempfile.TemporaryDirectory() as tmpdir:
                    zipped_archive_name = archive.name + ".zip"
                    zipped_archive = tmpdir / Path(zipped_archive_name)
                    flat_folder_to_zip(archive, zipped_archive)
                    return await __do_upload(zipped_archive, zipped_archive_name)
            else:
                return await __do_upload(archive, file_name)

    if lock.writer.locked or lock.reader.locked:
        logger.warning("[upload_archives] Lock conflict, backing off.")
        return
    async with lock.writer_lock:
        # find all archives
        logger.info("[upload_archives] Scanning archive directory; this may take a while...")
        start_time = time.time()
        if archive_is_dir:
            archives = find_all_leaf_folders(upload_dir)
        else:
            archives = find_all_archives(upload_dir)

        logger.info(f"[upload_archives] Uploading {len(archives)} archives...")

        tasks = [asyncio.create_task(__handle_archive(archive)) for archive in archives]
        upload_success = sum(await asyncio.gather(*tasks))
        total_time = time.time() - start_time
        logger.info(f"[upload_archives] {upload_success} archives uploaded. Total time: {total_time}s.")
