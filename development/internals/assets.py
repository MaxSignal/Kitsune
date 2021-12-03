from configs.env_vars import CONSTANTS
from development.utils import get_folder_file_paths

file_extensions = ['gif', 'jpeg', 'jpg', 'png', 'webp']
assets_folder = CONSTANTS.DEV_PATH.joinpath('assets')
asset_files = get_folder_file_paths(assets_folder, file_extensions)
