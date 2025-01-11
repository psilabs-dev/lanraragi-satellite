import hashlib
from pathlib import Path
import tempfile
from typing import Union
import zipfile

import pytest

from manycbz.comic import create_comic
from manycbz.enums import ArchivalStrategyEnum
from manycbz.page import Page

def calculate_sha1(path: Union[Path, str]):
    if isinstance(path, str):
        path = Path(path)
    sha1 = hashlib.sha1()
    with open(path, 'rb') as reader:
        while chunk := reader.read(8192):
            sha1.update(chunk)
        return sha1.hexdigest()

def test_create_zip_archive():
    comic_id = 'test-comic-out'
    width = 1200
    height = 1700
    num_pages = 20
    for page_id in [1, 3, 9, 10, 20]:
        page_name = f"pg-{str(page_id).zfill(len(str(num_pages)))}"
        yield (comic_id, width, height, num_pages, page_id, page_name)

@pytest.mark.parametrize('comic_id, width, height, num_pages, page_id, page_name', test_create_zip_archive())
def test_create_zip_archive(comic_id: str, width: int, height: int, num_pages: int, page_id: int, page_name: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        save_image_path = Path(tmpdir) / "expected-image.png"
        expected_pg_1001 = Page(1200, 1700)
        expected_pg_1001.whiten_panel()
        expected_pg_1001.add_panel_boundary()
        expected_pg_1001.write_text(f"{comic_id}-{page_name}")
        expected_pg_1001.save(save_image_path)
        expected_sha1 = calculate_sha1(save_image_path)

        save_zip_path = Path(tmpdir) / "output.zip"
        create_comic(save_zip_path, comic_id, width, height, num_pages, archival_strategy=ArchivalStrategyEnum.ZIP)

        output_dir = Path(tmpdir) / "output"
        with zipfile.ZipFile(save_zip_path, 'r') as zip_ref:
            zip_ref.extractall(output_dir)
        actual_sha1 = calculate_sha1(output_dir / f"{page_name}.png")
        assert actual_sha1 == expected_sha1