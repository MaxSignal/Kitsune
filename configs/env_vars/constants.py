from pathlib import Path


class CONSTANTS:
    PROJECT_PATH = Path(__file__, '..', '..').resolve()
    DEV_PATH = PROJECT_PATH.joinpath('development')
    DOWNLOAD_PATH = Path('/storage')
    DATA_FOLDER = DOWNLOAD_PATH.joinpath('data')
    TEMP_DIR_ROOT = DATA_FOLDER.joinpath('tmp')
