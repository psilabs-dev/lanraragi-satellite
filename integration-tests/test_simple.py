"""
Collection of all simple API testing pipelines for the LANraragi server.

For each testing pipeline, a new network, server and database are allocated and reclaimed.
This provides every test with an isolated environment.
"""

import asyncio
import logging
from pathlib import Path
import tempfile
from typing import Generator, List
import docker
import numpy as np
import pytest
from lanraragi.client import LRRClient
from lanraragi.docker_testing.environment import LRREnvironment
from lanraragi.utils import compute_upload_checksum
from manycbz.enums import ArchivalStrategyEnum
from manycbz.models import CreatePageRequest, WriteArchiveRequest, WriteArchiveResponse
from manycbz.service.archive import write_archives_to_disk
from manycbz.service.metadata import create_tag_generators, get_tag_assignments

logger = logging.getLogger(__name__)

@pytest.fixture(autouse=True)
def session_setup_teardown(request: pytest.FixtureRequest):
    build_path: str = request.config.getoption("--build")
    image: str = request.config.getoption("--image")
    git_url: str = request.config.getoption("--git-url")
    git_branch: str = request.config.getoption("--git-branch")
    use_docker_api: bool = request.config.getoption("--docker-api")
    docker_client = docker.from_env()
    docker_api = docker.APIClient(base_url="unix://var/run/docker.sock") if use_docker_api else None
    environment = LRREnvironment(build_path, image, git_url, git_branch, docker_client, docker_api=docker_api)
    environment.setup()
    yield
    environment.teardown()

@pytest.fixture
def semaphore():
    yield asyncio.Semaphore(value=8)

@pytest.fixture
def lanraragi() -> Generator[LRRClient, None, None]:
    yield LRRClient(lrr_host="http://localhost:3001", lrr_api_key="lanraragi")

async def upload_archive(client: LRRClient, save_path: Path, filename: str, semaphore: asyncio.Semaphore, checksum: str=None, title: str=None, tags: str=None):
    async with semaphore:
        return await client.upload_archive(save_path, filename, title=title, tags=tags, archive_checksum=checksum)

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
async def test_archive_upload(lanraragi: LRRClient, semaphore: asyncio.Semaphore):
    """
    Creates 100 archives to upload to the LRR server, 
    then verifies that this number of archives is correct.
    """
    generator = np.random.default_rng(42)
    num_archives = 100

    # >>>>> TEST CONNECTION STAGE >>>>>
    assert (await lanraragi.get_server_info()).status_code == 200, "Cannot connect to the LANraragi server!"
    logger.debug("Established connection with test LRR server.")
    # verify we are working with a new server.
    assert len((await lanraragi.get_all_archives()).data) == 0, "Server contains archives!"
    # <<<<< TEST CONNECTION STAGE <<<<<

    # >>>>> UPLOAD STAGE >>>>>
    tag_generators = create_tag_generators(100, pmf)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        logger.debug(f"Creating {num_archives} archives to upload.")
        write_responses = save_archives(num_archives, tmpdir, generator)
        assert len(write_responses) == num_archives, f"Number of archives written does not equal {num_archives}!"

        # archive metadata
        logger.debug("Uploading archives to server.")
        tasks = []
        for i, _response in enumerate(write_responses):
            title = f"Archive {i}"
            tags = ','.join(get_tag_assignments(tag_generators, generator))
            checksum = compute_upload_checksum(_response.save_path)
            tasks.append(asyncio.create_task(
                upload_archive(lanraragi, _response.save_path, _response.save_path.name, semaphore, title=title, tags=tags, checksum=checksum)
            ))
        gathered = await asyncio.gather(*tasks)
        for gather in gathered:
            assert gather.status_code == 200, f"Upload status code is not 200: {gather.status_code}"
    # <<<<< UPLOAD STAGE <<<<<

    # >>>>> VALIDATE UPLOAD COUNT STAGE >>>>>
    logger.debug("Validating upload counts.")
    response = await lanraragi.get_all_archives()
    assert response.status_code == 200, f"Failed to get archive data: {response.error}"
    assert len(response.data) == num_archives, "Number of archives on server does not equal number uploaded!"
    # <<<<< VALIDATE UPLOAD COUNT STAGE <<<<<

@pytest.mark.asyncio
@pytest.mark.experimental
async def test_category(lanraragi: LRRClient, semaphore: asyncio.Semaphore):
    """
    Runs sanity tests against the category and highlight API.

    TODO: a more comprehensive test should be designed to verify that the first-time installation
    does not apply when a server is restarted. This should preferably be in a separate test module
    that is more involved with the server environment.
    """
    # >>>>> TEST CONNECTION STAGE >>>>>
    assert (await lanraragi.get_server_info()).status_code == 200, "Cannot connect to the LANraragi server!"
    logger.debug("Established connection with test LRR server.")
    # verify we are working with a new server.
    assert len((await lanraragi.get_all_archives()).data) == 0, "Server contains archives!"
    # <<<<< TEST CONNECTION STAGE <<<<<

    # >>>>> GET HIGHLIGHT >>>>>
    category_id = (await lanraragi.get_bookmark_link()).category_id
    category_name = (await lanraragi.get_category(category_id)).data.get("name")
    assert category_name == 'Favorites', "Default highlight is not Favorites!"
    # <<<<< GET HIGHLIGHT <<<<<

    # >>>>> CREATE CATEGORY >>>>>
    static_cat_id = (await lanraragi.create_category("test-static-category")).category_id
    dynamic_cat_id = (await lanraragi.create_category("test-dynamic-category", search="language:english")).category_id
    # <<<<< CREATE CATEGORY <<<<<

    # >>>>> UPDATE CATEGORY >>>>>
    assert (await lanraragi.update_category(static_cat_id, name="test-static-category-changed")).status_code == 200, "Failed to update category ID!"
    assert (await lanraragi.get_category(static_cat_id)).data.get("name") == "test-static-category-changed", "Category ID name is incorrect after update!"
    # <<<<< UPDATE CATEGORY <<<<<

    # >>>>> UPDATE HIGHLIGHT >>>>>
    assert (await lanraragi.update_bookmark_link(static_cat_id)).status_code == 200, "Updating highlight was not success"
    assert (await lanraragi.update_bookmark_link(dynamic_cat_id)).status_code == 400, "Assigning highlight to dynamic category should not be possible!"
    assert (await lanraragi.get_bookmark_link()).category_id == static_cat_id, "Highlight after category update is incorrect!"
    # <<<<< UPDATE HIGHLIGHT <<<<<

    # >>>>> DELETE HIGHLIGHT >>>>>
    await lanraragi.remove_bookmark_link()
    assert not (await lanraragi.get_bookmark_link()).category_id
    # <<<<< DELETE HIGHLIGHT <<<<<

    # >>>>> DELETE HIGHLIGHTED CATEGORY >>>>>
    static_cat_id_2 = (await lanraragi.create_category("test-static-category-2")).category_id
    assert (await lanraragi.update_bookmark_link(static_cat_id_2)).status_code == 200, "Updating highlight was not success"
    assert (await lanraragi.get_bookmark_link()).category_id == static_cat_id_2, "Highlight after category update is incorrect!"
    assert (await lanraragi.delete_category(static_cat_id_2)).status_code == 200, "Failed to delete highlighted category!"
    assert not (await lanraragi.get_bookmark_link()).category_id, "Deleting a highlighted category should remove highlight!"
    # <<<<< DELETE HIGHLIGHTED CATEGORY <<<<<
