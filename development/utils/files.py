import os
import tempfile
from pathlib import Path
from typing import List
from uuid import uuid4

from configs.env_vars import CONSTANTS
from src.internals.utils.utils import get_hash_of_file


def get_folder_file_paths(folder: Path, extensions: List[str] = None) -> List[Path]:
    """
    Reads the folder shallowly at provided absolute path.
    Returns a list of absolute paths for files inside it.
    If the list of extensions provided,
    limits the resulting list to the files with these extensions.
    """
    if not folder.is_absolute():
        raise ValueError(f'Path "{folder}" is not absolute.')

    if not folder.is_dir():
        raise ValueError(f'Path "{folder}" is not a folder.')

    files = []
    if not extensions:
        for path in folder.iterdir():
            if path.is_file():
                files.append(path)
                continue
    else:
        for path in folder.iterdir():
            if path.is_file() and path.suffix and path.suffix[1:] in extensions:
                files.append(path)
                continue

    return files


def create_temporary_directory() -> Path:
    """
    Creates temporary directory.
    """
    os.makedirs(CONSTANTS.TEMP_DIR_ROOT, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=str(CONSTANTS.TEMP_DIR_ROOT))
    temp_name = f'{str(uuid4())}.temp'
    temp_path = Path(temp_dir, temp_name)
    return temp_path


def generate_hashy_filename(file_path: Path, extension: str):
    """
    Generates unique filename.
    """
    file_hash = get_hash_of_file(file_path)
    hash_filename = Path(file_hash[0:2], file_hash[2:4], file_hash + extension)
    return hash_filename
