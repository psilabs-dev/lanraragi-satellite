from pathlib import Path
from typing import List, Union, overload

from satellite.utils.lanraragi.constants import ALLOWED_SIGNATURES


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
