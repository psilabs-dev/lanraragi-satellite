import hashlib
from pathlib import Path
import tempfile  # noqa: F401
from typing import Union

from manycbz.page import Page  # noqa: F401

def calculate_sha1(path: Union[Path, str]):
    if isinstance(path, str):
        path = Path(path)
    sha1 = hashlib.sha1()
    with open(path, 'rb') as reader:
        while chunk := reader.read(8192):
            sha1.update(chunk)
        return sha1.hexdigest()

# def test_create_page():
#     expected_checksum = calculate_sha1('tests/manycbz/resources/test-page-1.png')
#     with tempfile.TemporaryDirectory() as tmpdir:
#         save = Path(tmpdir) / "output.png"
#         page = Page(1280, 1780)
#         page.whiten_panel()
#         page.add_panel_boundary()
#         page.write_text('test text')
#         page.save(save)
#         actual_checksum = calculate_sha1(save)
#         page.close()
#     assert actual_checksum == expected_checksum, "Created image does not match expected image."

# def test_create_corrupted_page():
#     expected_checksum = calculate_sha1('tests/manycbz/resources/test-corrupted-page-1.png')
#     with tempfile.TemporaryDirectory() as tmpdir:
#         save = Path(tmpdir) / "output.png"
#         page = Page(1280, 1780, first_n_bytes=1000)
#         page.save(save)
#         actual_checksum = calculate_sha1(save)
#         page.close()
#     assert actual_checksum == expected_checksum, "Created corrupted image does not match expected corrupted image."
