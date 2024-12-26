import hashlib
import io
from pathlib import Path
from typing import overload, Union


@overload
def compute_upload_checksum(br: io.IOBase) -> str:
    ...

@overload
def compute_upload_checksum(file_path: Path) -> str:
    ...

@overload
def compute_upload_checksum(file_path: str) -> str:
    ...

def compute_upload_checksum(file: Union[io.IOBase, Path, str]) -> str:
    """
    Compute the SHA1 hash of an Archive before an upload for in-transit integrity checks.
    """
    sha1 = hashlib.sha1()
    if isinstance(file, io.IOBase):
        while chunk := file.read(8192):
            sha1.update(chunk)
        return sha1.hexdigest()
    elif isinstance(file, (Path, str)):
        with open(file, 'rb') as file_br:
            while chunk := file_br.read(8192):
                sha1.update(chunk)
            return sha1.hexdigest()
    else:
        raise TypeError(f"Unsupported file type {type(file)}")
