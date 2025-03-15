"""
Image analysis library.
"""
from pathlib import Path
import tempfile
from typing import overload, Union
import zipfile

def image_is_incomplete_bytes(image: Union[str, Path, bytes]):
    """
    Determine if an image file is incomplete based on its byte content.
    Returns True if the image is incomplete (truncated/corrupted), or False if it is complete.
    Supported formats: JPEG, PNG, TIFF.
    """
    # Accept str or Path for the file path
    if not isinstance(image, (str, Path)):
        raise TypeError(f"Expected a file path (str or Path), got {type(image)}")
    path = Path(image)
    with path.open("rb") as f:
        file_size = path.stat().st_size
        if file_size == 0:
            return True
        header = f.read(8)
        if header[:2] == b'\xFF\xD8': # JPG
            f.seek(file_size - 2)
            eof_bytes = f.read(2)
            return eof_bytes != b'\xFF\xD9'
        elif header[:8] == b'\x89PNG\r\n\x1a\n': # PNG
            f.seek(file_size - 8)
            eof_bytes = f.read(8)
            expected_png_eof = b'\x49\x45\x4E\x44\xAE\x42\x60\x82'
            return eof_bytes != expected_png_eof
        else:
            raise TypeError(f"Expected JPEG, PNG or TIFF file: {image}")

@overload
def archive_contains_incomplete_image(archive_path: str) -> bool:
    ...

@overload
def archive_contains_incomplete_image(archive_path: Path) -> bool:
    ...

def archive_contains_incomplete_image(archive_path: Union[Path, str]) -> bool:
    """
    Quick-and-dirty method to check if a zip Archive contains an incomplete image.
    """
    if isinstance(archive_path, str):
        archive_path = Path(archive_path)
    if archive_path.suffix and archive_path.suffix[1:] not in {"zip", "cbz"}:
        # non-zip archives are currently not supported.
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        extracted_archive_folder = Path(tmpdir) / archive_path.name
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            zip_ref.extractall(extracted_archive_folder)
            for image in extracted_archive_folder.iterdir():
                if image.suffix.lower() in {".png", ".jpg", ".jpeg"} and image_is_incomplete_bytes(image):
                    return True
    return False
