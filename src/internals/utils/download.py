import mimetypes
import requests
import uuid
import cgi
import re
import shutil
import functools
import urllib
import config
import tempfile
import os
import magic
import re
import pathlib
import datetime
from PIL import Image
from os import rename, makedirs, remove
from os.path import join, getsize, exists, splitext, basename, dirname
from .proxy import get_proxy
from .utils import get_hash_of_file
from ...lib.files import write_file_log

non_url_safe = ['"', '#', '$', '%', '&', '+',
    ',', '/', ':', ';', '=', '?',
    '@', '[', '\\', ']', '^', '`',
    '{', '|', '}', '~', "'"]

class DuplicateException(Exception):
    pass

class DownloaderException(Exception):
    pass

def uniquify(path):
    filename, extension = splitext(path)
    counter = 1

    while exists(path.encode('utf-8')):
        path = filename + "_" + str(counter) + extension
        counter += 1

    return basename(path)

def get_filename_from_cd(cd):
    if not cd:
        return None
    fname = re.findall(r"filename\*=([^;]+)", cd, flags=re.IGNORECASE)
    if len(fname) == 0:
        return None
    if not fname:
        fname = re.findall("filename=([^;]+)", cd, flags=re.IGNORECASE)
    if "utf-8''" in fname[0].lower():
        fname = re.sub("utf-8''", '', fname[0], flags=re.IGNORECASE)
        fname = urllib.parse.unquote(fname)
    else:
        fname = fname[0]
    # clean space and double quotes
    return fname.strip().strip('"')

def slugify(text):
    """
    Turn the text content of a header into a slug for use in an ID
    """
    non_safe = [c for c in text if c in non_url_safe]
    if non_safe:
        for c in non_safe:
            text = text.replace(c, '')
    # Strip leading, trailing and multiple whitespace, convert remaining whitespace to _
    text = u'_'.join(text.split())
    return text

def download_branding(ddir, url, name = None, **kwargs):
    temp_name = str(uuid.uuid4()) + '.temp'
    tries = 10
    makedirs(ddir, exist_ok=True)
    for i in range(tries):
        try:
            r = requests.get(url, stream = True, proxies=get_proxy(), **kwargs)
            r.raw.read = functools.partial(r.raw.read, decode_content=True)
            r.raise_for_status()
            # Should retry on connection error
            with open(join(ddir, temp_name), 'wb+') as file:
                shutil.copyfileobj(r.raw, file)
                # filename guessing
                mimetype, _ = cgi.parse_header(r.headers['content-type'])
                extension = mimetypes.guess_extension(mimetype, strict=False) if r.headers.get('content-type') else None
                extension = extension or '.txt'
                filename = name or r.headers.get('x-amz-meta-original-filename')
                if filename is None:
                    filename = get_filename_from_cd(r.headers.get('content-disposition')) or (str(uuid.uuid4()) + extension)
                filename = slugify(filename)
                # ensure unique filename
                filename = uniquify(join(ddir, filename))
                # content integrity
                if r.headers.get('content-length') and r.raw.tell() < int(r.headers.get('content-length')):
                    reported_size = r.raw.tell()
                    downloaded_size = r.headers.get('content-length')
                    raise DownloaderException(f'Downloaded size is less than reported; {downloaded_size} < {reported_size}')

                file.close()
                rename(join(ddir, temp_name), join(ddir, filename))
                
                make_thumbnail(join(ddir, filename))

                return filename, r
        except requests.HTTPError as e:
            raise e
        except:
            if i < tries - 1: # i is zero indexed
                continue
            else:
                raise
        break

def download_file(
    url: str,
    service,
    user,
    post,
    name: str = None,
    inline: bool = False,
    discord: bool = False,
    discord_message_server: str = '',
    discord_message_channel: str = '',
    discord_message_id: str = '',
    **kwargs
):
    makedirs(join(config.download_path, 'data', 'tmp'), exist_ok=True)
    temp_dir = tempfile.mkdtemp(dir=join(config.download_path, 'data', 'tmp'))
    temp_name = str(uuid.uuid4()) + '.temp'
    tries = 10
    for i in range(tries):
        try:
            r = requests.get(url, stream = True, proxies=get_proxy(), **kwargs)
            r.raw.read = functools.partial(r.raw.read, decode_content=True)
            r.raise_for_status()
            # Should retry on connection error
            with open(join(temp_dir, temp_name), 'wb+') as file:
                shutil.copyfileobj(r.raw, file)
                # filename guessing
                reported_mime, _ = cgi.parse_header(r.headers['content-type']) if r.headers.get('content-type') else (None, None)
                mime = magic.from_file(join(temp_dir, temp_name), mime=True)
                extension = re.sub('^.jpe$', '.jpg', mimetypes.guess_extension(mime or reported_mime or 'application/octet-stream', strict=False) or '.bin')
                reported_filename = name or r.headers.get('x-amz-meta-original-filename') or get_filename_from_cd(r.headers.get('content-disposition')) or (str(uuid.uuid4()) + extension)
                
                # content integrity
                if r.headers.get('content-length') and r.raw.tell() < int(r.headers.get('content-length')):
                    reported_size = r.raw.tell()
                    downloaded_size = r.headers.get('content-length')
                    raise DownloaderException(f'Downloaded size is less than reported; {downloaded_size} < {reported_size}')

                # generate hashy filename
                # this will be the one we actually save the file with
                file_hash = get_hash_of_file(join(temp_dir, temp_name))
                hash_filename = join(file_hash[0:2], file_hash[2:4], file_hash + extension)

                fname = pathlib.Path(join(temp_dir, temp_name))
                mtime = datetime.datetime.fromtimestamp(fname.stat().st_mtime)
                ctime = datetime.datetime.fromtimestamp(fname.stat().st_ctime)
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
                    url,
                    discord=discord,
                    discord_message_server=discord_message_server,
                    discord_message_channel=discord_message_channel,
                    discord_message_id=discord_message_id
                )

                if (exists(join(config.download_path, 'data', hash_filename))):
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    return reported_filename, '/' + hash_filename, r
                
                file.close()
                
                makedirs(join(config.download_path, 'data', file_hash[0:2], file_hash[2:4]), exist_ok=True)
                rename(join(temp_dir, temp_name), join(config.download_path, 'data', hash_filename))
                shutil.rmtree(temp_dir, ignore_errors=True)
                make_thumbnail(join(config.download_path, 'data', hash_filename))
                return reported_filename, '/' + hash_filename, r
        except requests.HTTPError as e:
            raise e
        except:
            if i < tries - 1: # i is zero indexed
                continue
            else:
                raise
        break

def make_thumbnail(path):
    try:
        image = Image.open(path)
        image = image.convert('RGB')
        image.thumbnail((800, 800))
        makedirs(dirname(join(config.download_path, 'thumbnail' + path.replace(config.download_path, ''))), exist_ok=True)
        image.save(join(config.download_path, 'thumbnail' + path.replace(config.download_path, '')), 'JPEG', quality=60)
    except:
        pass
