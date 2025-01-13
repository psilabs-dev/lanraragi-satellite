import numpy as np
from pathlib import Path
from PIL import Image
import tempfile
from typing import overload, Union
import zipfile

@overload
def image_is_corrupted(image_path: str) -> bool:
    ...

@overload
def image_is_corrupted(image_path: Path) -> bool:
    ...

@overload
def image_is_corrupted(image: Image.Image) -> bool:
    ...

def image_is_corrupted(image: Union[Image.Image, Path, str]) -> bool:
    """
    Quick-and-dirty method to check if an image is corrupted.
    """
    if isinstance(image, Image.Image):
        try:
            np.asarray(image)
            return False
        except OSError: # this is thrown by numpy whenever we have a corrupted image.
            return True

    if isinstance(image, str):
        image = Path(image)
    if not isinstance(image, Path):
        raise TypeError(f"Unsupported image path type: {type(image)}")
    
    # if the image has zero bytes, then we have a problem.
    if image.stat().st_size == 0:
        return True
    image = Image.open(image)
    return image_is_corrupted(image)

@overload
def archive_contains_corrupted_image(archive_path: str) -> bool:
    ...

@overload
def archive_contains_corrupted_image(archive_path: Path) -> bool:
    ...

def archive_contains_corrupted_image(archive_path: Union[Path, str]) -> bool:
    """
    Quick-and-dirty method to check if a zip Archive contains a corrupted image.
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
                if image.suffix.lower() in {".png", ".jpg", ".jpeg"} and image_is_corrupted(image):
                    return True
    return False
