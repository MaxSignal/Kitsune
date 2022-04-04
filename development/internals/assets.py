# from pathlib import Path
import os

from configs.constants import DEV_PATH
from development.utils import get_folder_file_paths

file_extensions = ['gif', 'jpeg', 'jpg', 'png', 'webp']
assets_folder = DEV_PATH.joinpath('assets')

if not assets_folder.exists():
    os.makedirs(assets_folder, exist_ok=True)

asset_files = get_folder_file_paths(assets_folder, file_extensions)
