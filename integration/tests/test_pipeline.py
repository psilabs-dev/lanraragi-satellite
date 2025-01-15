"""
API testing pipelines for a LANraragi server.
"""

import asyncio
import logging
from pathlib import Path
import tempfile
from typing import List
import numpy as np
import pytest
from lanraragi.client import LRRClient
from manycbz.enums import ArchivalStrategyEnum
from manycbz.models import CreatePageRequest, WriteArchiveRequest, WriteArchiveResponse
from manycbz.service.archive import write_archives_to_disk
from manycbz.service.metadata import create_tag_generators, get_tag_assignments

logger = logging.getLogger(__name__)
semaphore = asyncio.Semaphore(value=8)

async def upload_archive(client: LRRClient, save_path: Path, filename: str, title: str=None, tags: str=None):
    async with semaphore:
        return await client.upload_archive(save_path, filename, title=title, tags=tags)

def get_client():
    return LRRClient(lrr_host="http://localhost:3000", lrr_api_key="lanraragi")

def pmf(t: float) -> float:
    return 2 ** (-t * 100)

def save_archives(num_archives: int, work_dir: Path, np_generator: np.random.Generator) -> List[WriteArchiveResponse]:
    requests = []
    responses = []
    for archive_id in range(num_archives):
        create_page_requests = []
        archive_name = f"archive-{str(archive_id+1).zfill(len(str(num_archives)))}"
        filename = f"{archive_name}.zip"
        save_path = work_dir / filename
        num_pages = np_generator.integers(10, 20)
        for page_id in range(num_pages):
            page_text = f"{archive_name}-pg-{str(page_id+1).zfill(len(str(num_pages)))}"
            page_filename = f"{page_text}.png"
            create_page_request = CreatePageRequest(1080, 1920, page_filename, image_format='PNG', text=page_text)
            create_page_requests.append(create_page_request)        
        requests.append(WriteArchiveRequest(create_page_requests, save_path, ArchivalStrategyEnum.ZIP))
    responses = write_archives_to_disk(requests)
    return responses

@pytest.mark.asyncio
@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")
async def test_pipeline_1():
    client = get_client()
    generator = np.random.default_rng(42)
    num_archives = 100

    # >>>>> TEST CONNECTION STAGE >>>>>
    assert (await client.get_server_info()).status_code == 200, "Cannot connect to the LANraragi server!"
    logger.info("Established connection with test LRR server.")
    # verify we are working with a new server.
    assert len((await client.get_all_archives()).data) == 0, "Server contains archives!"
    # <<<<< TEST CONNECTION STAGE <<<<<

    # >>>>> UPLOAD STAGE >>>>>
    tag_generators = create_tag_generators(100, pmf)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        logger.info(f"Creating {num_archives} archives to upload.")
        write_responses = save_archives(num_archives, tmpdir, generator)
        assert len(write_responses) == num_archives, f"Number of archives written does not equal {num_archives}!"

        # archive metadata
        logger.info("Uploading archives to server.")
        tasks = []
        for i, _response in enumerate(write_responses):
            title = f"Archive {i}"
            tags = ','.join(get_tag_assignments(tag_generators, generator))
            tasks.append(asyncio.create_task(
                upload_archive(client, _response.save_path, _response.save_path.name, title=title, tags=tags)
            ))
        gathered = await asyncio.gather(*tasks)
        for gather in gathered:
            assert gather.status_code == 200, f"Upload status code is not 200: {gather.status_code}"
    # <<<<< UPLOAD STAGE <<<<<

    # >>>>> VALIDATE UPLOAD COUNT STAGE >>>>>
    logger.info("Validating upload counts.")
    response = await client.get_all_archives()
    assert response.status_code == 200, f"Failed to get archive data: {response.error}"
    assert len(response.data) == num_archives, "Number of archives on server does not equal number uploaded!"
    # <<<<< VALIDATE UPLOAD COUNT STAGE <<<<<
