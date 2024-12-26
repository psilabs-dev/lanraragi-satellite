import hashlib
from pathlib import Path
from typing import Union, overload

from satellite.utils.lanraragi.constants import NULL_ARCHIVE_ID


@overload
def compute_archive_id(file_path: str) -> str:
    ...

@overload
def compute_archive_id(file_path: Path) -> str:
    ...

def compute_archive_id(file_path: Union[Path, str]) -> str:
    """
    Compute the ID of a file in the same way as the server.
    """
    if isinstance(file_path, (Path, str)):
        with open(file_path, 'rb') as fb:
            data = fb.read(512000)
        
        sha1 = hashlib.sha1()
        sha1.update(data)
        digest = sha1.hexdigest()
        if digest == NULL_ARCHIVE_ID:
            raise ValueError("Computed ID is for a null value, invalid source file.")
        return digest
    else:
        raise TypeError(f"Unsupported type: {type(file_path)}")