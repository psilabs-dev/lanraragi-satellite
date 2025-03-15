"""
Archive file/folder discovery library.
"""
from pathlib import Path
from typing import List, Union, overload

from lanraragi.constants import ALLOWED_LRR_EXTENSIONS


@overload
def discover_all_archives_in_folder(root_directory: str) -> List[Path]:
    ...

@overload
def discover_all_archives_in_folder(root_directory: Path) -> List[Path]:
    ...

def discover_all_archives_in_folder(root_directory: Union[Path, str]) -> List[Path]:
    """
    Find all files in a directory with qualifying file extensions.
    """
    if isinstance(root_directory, str):
        root_directory = Path(root_directory)

    if isinstance(root_directory, Path):
        file_paths = []
        for item in root_directory.rglob("*"):
            suffix = item.suffix
            if not suffix:
                continue
            if suffix[1:] not in ALLOWED_LRR_EXTENSIONS:
                continue
            file_paths.append(item)
        return file_paths
    else:
        raise TypeError(f"Unsupported root directory type: {type(root_directory)}")

@overload
def discover_all_leaf_folders(root_directory: str) -> List[Path]:
    ...

@overload
def discover_all_leaf_folders(root_directory: Path) -> List[Path]:
    ...

def discover_all_leaf_folders(root_directory: Union[Path, str]) -> List[Path]:
    """
    Find all folders in a root directory that do not contain folders.
    """
    if isinstance(root_directory, str):
        root_directory = Path(root_directory)
    
    if isinstance(root_directory, Path):
        leafs = []
        for subdir in root_directory.rglob("*"):
            if subdir.is_dir() and not any(subsubdir.is_dir() for subsubdir in subdir.iterdir()):
                leafs.append(subdir)
        return leafs
    else:
        raise TypeError(f"Unsupported root directory type: {type(root_directory)}")