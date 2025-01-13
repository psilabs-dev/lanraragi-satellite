

from pathlib import Path
import tempfile
from manycbz.models import CreatePageRequest
from manycbz.service.page import create_page, save_page_to_dir
from satellite_server.utils.image import image_is_corrupted

def test_image_is_corrupted():

    # example of a not corrupted image.
    image = create_page(CreatePageRequest(1280, 1779, "corrupted_image.png")).page.image
    assert not image_is_corrupted(image), "Uncorrupted image is flagged as corrupted!"

    page = create_page(CreatePageRequest(1280, 1779, "corrupted_image.png", first_n_bytes=1000)).page
    with tempfile.TemporaryDirectory() as tmpdir:
        save_page_to_dir(page, Path(tmpdir))
        assert image_is_corrupted(Path(tmpdir) / "corrupted_image.png"), "Corrupted image is not flagged as corrupted!"
