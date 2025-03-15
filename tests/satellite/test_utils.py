

from pathlib import Path
import tempfile
from manycbz.models import CreatePageRequest
from manycbz.service.page import create_page, save_page_to_dir
from satellite.utils.image import image_is_incomplete_bytes

def test_image_is_corrupted():

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        page = create_page(CreatePageRequest(1280, 1779, "corrupted_image.png")).page
        save_page_to_dir(page, tmpdir)
        assert not image_is_incomplete_bytes(tmpdir / page.filename), "Uncorrupted image is flagged as corrupted!"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        page = create_page(CreatePageRequest(1280, 1779, "corrupted_image.png", first_n_bytes=1000)).page
        save_page_to_dir(page, tmpdir)
        assert image_is_incomplete_bytes(tmpdir / page.filename), "Corrupted image is not flagged as corrupted!"
