from src.internals.utils.download import perform_copy, make_thumbnail
from src.internals.utils.utils import get_hash_of_file
from src.internals.cache.redis import get_redis
from src.internals.utils.logger import log
from src.lib.files import write_file_log

from pyjd.direct_connector import DirectConnector
from pyjd.linkgrabber import LinkGrabber
from pyjd.downloads import Downloads
from urllib.parse import quote
from os.path import join
from retry import retry

from pyjd.jd_types import (
    LinkCrawlerJobsQuery,
    CrawledPackageQuery,
    AvailableLinkState,
    CrawledLinkQuery,
    AddLinksQuery,
    DownloadLink,
    PackageQuery,
    LinkQuery
)

import mimetypes
import datetime
import pathlib
import config
import shutil
import magic
import json
import time
import os
import re


class JobStartTimeoutException(Exception):
    pass


def download_not_in_set_filter(_set: set):
    def is_download_uuid_not_in_set(download: DownloadLink) -> bool:
        return download.uuid not in _set
    return is_download_uuid_not_in_set


def get_download_location(downloader: Downloads, download: DownloadLink) -> str:
    package_query = PackageQuery.default().__dict__ | dict(packageUUIDs=[download.packageUUID])
    (package,) = downloader.query_packages(PackageQuery(**package_query))
    return join(package.saveTo, download.name)


def wait_for_job_start(grabber: LinkGrabber, job_id: int, timeout=10):
    # Wait until job finishes crawling.
    time_at_start = time.time()
    while True:
        if time.time() > time_at_start + timeout:
            raise JobStartTimeoutException('Timed out while waiting for job to start')
        (job_status, *_) = grabber.query_link_crawler_jobs(LinkCrawlerJobsQuery(
            collectorInfo=True,
            jobIds=[job_id]
        )) + [None]
        if not job_status:
            continue
        if not job_status.crawling and not job_status.checking:
            break


def process_download(
    downloader: Downloads,
    download: DownloadLink,
    service=None,
    user_id=None,
    post_id=None
):
    download_original_name = download.name
    download_size = download.bytesTotal
    download_url = download.url
    download_path = get_download_location(downloader, download)
    mime = magic.from_file(download_path, mime=True)
    extension = re.sub(
        '^.jpe$',
        '.jpg',
        mimetypes.guess_extension(mime or 'application/octet-stream', strict=False) or '.bin'
    )
    # Generate hashpath...
    file_hash = get_hash_of_file(download_path)
    hash_filename = join(file_hash[0:2], file_hash[2:4], file_hash + extension)
    # ...write file logs,
    fname = pathlib.Path(download_path)
    mtime = datetime.datetime.fromtimestamp(fname.stat().st_mtime)
    ctime = datetime.datetime.fromtimestamp(fname.stat().st_ctime)
    if service and user_id and post_id:
        write_file_log(
            file_hash, mtime, ctime, mime, extension,
            download_original_name, service, user_id,
            post_id, False, download_url,
            download_size
        )
    # ...and copy the file to the permanent destination.
    perform_copy(
        download_path,
        join(config.data_download_path, 'data', hash_filename),
        rsync=config.rsync_data_host,
        options=config.rsync_data_options
    )


@retry(JobStartTimeoutException, tries=3)
def import_posts(import_id, key_data):
    r = get_redis()
    data = json.loads(r.get(f'imports:{import_id}'))
    # In the Jdownloader2 importer, the "key" is the link data
    #   that will be processed... it's perhaps a bit a strange
    #   in the grand scheme of things, but please bear with me
    #   on this one ^^''
    text_data = data['key']
    # Relations.
    service = data.get('service', None)
    post_id = data.get('user_id', None)
    user_id = data.get('post_id', None)

    def update_state(key=None, value=None):
        if key is not None and value is not None:
            data[key] = value
        r.set(f'imports:{import_id}', json.dumps(data, default=str))

    acceptable_statuses = ('Finished', 'File already exists')
    # It is required for Jdownloader2 to have the following setting;
    #   - Advanced Settings > RemoteAPI: Deprecated Api -> (enabled)
    # Recommended Jdownloader2 settings,
    # May not be necessary but prevents undesirable endcase behavior;
    #   - General > Download Management > If the file already exists -> Skip File
    #   - Archive Extractor: (disable)
    jdownloader = DirectConnector().get_device()
    downloader = Downloads(jdownloader)
    grabber = LinkGrabber(jdownloader)

    # Testing links;
    #   https://drive.google.com/file/d/193wHzgFfQ94xVxw-VmJsB_pSWQhg_RwV/view?usp=sharing
    #   https://drive.google.com/file/d/1ywxyWcQr63jQhbue-NNE8Z7FcjKiw1YR/view?usp=sharing
    #   https://drive.google.com/file/d/1hDl0O6rL-iFaJGK1XCDWHhWUyF5b7U-Q/view?usp=sharing
    #   https://en.wikipedia.org/wiki/Template_talk:Wstress3d
    job = grabber.add_links(AddLinksQuery(
        overwritePackagizerRules=True,
        autoExtract=False,
        assignJobID=True,
        links=quote(text_data)
    ))
    update_state('job_id', job.id)
    # Wait for a bit of time to prevent problems while the job is
    #   just starting up...
    time.sleep(2)
    # And then verify that whatever links that might have been
    #   found in the text have actually been crawled and are
    #   available to us for downloading.
    wait_for_job_start(grabber, job.id)

    link_query = CrawledLinkQuery.default().__dict__ | dict(jobUUIDs=[job.id])
    links = grabber.query_links(CrawledLinkQuery(**link_query))

    try:
        for link in links:
            if link.availability == AvailableLinkState.ONLINE:
                grabber.move_to_downloadlist([link.uuid], [link.packageUUID])
        download_query = LinkQuery.default().__dict__ | dict(jobUUIDs=[job.id])
        downloads = downloader.query_links(LinkQuery(**download_query))
        try:
            finished_download_uuids = set()
            downloads_to_process = downloads
            while len(downloads_to_process):
                for download in downloads_to_process:
                    if download.running:
                        # Download is still running...
                        continue
                    if download.finished or download.status in acceptable_statuses:
                        download_url = download.url
                        download_original_name = download.name
                        process_download(downloader, download, service, user_id, post_id)
                        log(import_id, f'Downloaded {download_url} ({download_original_name})')
                    else:
                        log(import_id, f'Download {download.url} failed... (status: {download.status})')
                    finished_download_uuids.add(download.uuid)
                # Update list of downloads.
                downloads = downloader.query_links(LinkQuery(**download_query))
                downloads_to_process_filter = download_not_in_set_filter(finished_download_uuids)
                downloads_to_process = list(filter(downloads_to_process_filter, downloads))
        finally:
            # Politely cleanup downloads for atomicity.
            for download in downloads:
                if os.path.exists(get_download_location(downloader, download)):
                    os.remove(get_download_location(downloader, download))
                downloader.remove_links([download.uuid], [download.packageUUID])
    finally:
        # Politely cleanup unprocessed links.
        for link in links:
            grabber.remove_links([link.uuid], [link.packageUUID])
    log(import_id, 'Finished downloading!')
