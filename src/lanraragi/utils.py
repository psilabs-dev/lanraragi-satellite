import hashlib
import io
from pathlib import Path
from typing import List, overload, Union

from lanraragi.constants import ALLOWED_SIGNATURES, NULL_ARCHIVE_ID


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


def get_source_from_tags(tags: str) -> Union[str, None]:
    """
    Return the source from tags if exists, else None.
    """
    tags = tags.split(',')
    for tag in tags:
        if tag.startswith("source:"):
            return tag[7:]
    return None


@overload
def get_signature_hex(archive_path: str) -> str:
    ...

@overload
def get_signature_hex(archive_path: Path) -> str:
    ...

def get_signature_hex(archive_path: Union[Path, str]) -> str:
    """
    Get first 8 bytes of archive in hex repr.
    """
    if isinstance(archive_path, (str, Path)):
        with open(archive_path, 'rb') as fb:
            signature = fb.read(24).hex()
            return signature
    else:
        raise TypeError(f"Unsupported file type: {type(archive_path)}")

def is_valid_signature_hex(signature: str, allowed_signatures: List[str]=ALLOWED_SIGNATURES) -> bool:
    """
    Check if the hex signature corresponds to a file type supported by LANraragi.
    """
    is_allowed_mime = False
    for allowed_signature in allowed_signatures:
        if signature.startswith(allowed_signature):
            is_allowed_mime = True
    return is_allowed_mime
