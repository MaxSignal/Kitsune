import os
import tempfile
import uuid
import shutil
import magic
import re
import mimetypes
from pathlib import Path
from datetime import datetime

from configs.env_vars import CONSTANTS
from src.internals.utils.utils import get_hash_of_file
from src.internals.utils.download import make_thumbnail
from src.lib.files import write_file_log
from development.types.models import File

data_folder = str(CONSTANTS.DATA_FOLDER)
temp_dir_root = str(CONSTANTS.TEMP_DIR_ROOT)


def download_file(
    file_path: str,
    service: str,
    user: str,
    post: str,
    file_name: str = None,
    inline: bool = False,
):
    os.makedirs(temp_dir_root, exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=temp_dir_root)
    temp_name = str(uuid.uuid4()) + '.temp'
    temp_path = os.path.join(temp_dir, temp_name)

    with open(temp_path, 'wb+') as file:
        shutil.copyfile(file_path, temp_path)
        # filename guessing
        mime = magic.from_file(temp_path, mime=True)
        extension = re.sub('^.jpe$', '.jpg', mimetypes.guess_extension(
            mime or 'application/octet-stream', strict=False) or '.bin')
        reported_filename = file_name or (str(uuid.uuid4()) + extension)

        # generate hashy filename
        # this will be the one we actually save the file with
        file_hash = get_hash_of_file(temp_path)
        hash_filename = os.path.join(file_hash[0:2], file_hash[2:4], file_hash + extension)

        fname = Path(temp_path)
        mtime = datetime.fromtimestamp(fname.stat().st_mtime)
        ctime = datetime.fromtimestamp(fname.stat().st_ctime)
        write_file_log(
            file_hash,
            mtime,
            ctime,
            mime,
            extension,
            reported_filename,
            service,
            user,
            post,
            inline,
            file_path,
        )

        if os.path.exists(os.path.join(data_folder, hash_filename)):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return File(
                name=reported_filename,
                path=f'/{hash_filename}',
            )

        file.close()

        os.makedirs(os.path.join(data_folder, file_hash[0:2], file_hash[2:4]), exist_ok=True)
        os.rename(temp_path, os.path.join(data_folder, hash_filename))
        shutil.rmtree(temp_dir, ignore_errors=True)
        make_thumbnail(os.path.join(data_folder, hash_filename))

        return File(
            name=reported_filename,
            path=f'/{hash_filename}',
        )
