from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.utils import get_value
from ..internals.utils.logger import log
from ..internals.utils.proxy import get_proxy
from ..internals.utils.download import download_file, DownloaderException
from ..internals.cache.redis import delete_keys
from ..lib.autoimport import encrypt_and_save_session_for_auto_import, kill_key
from ..lib.post import post_flagged, post_exists, delete_post_flags, move_to_backup, delete_backup, restore_from_backup, handle_post_import
from ..lib.artist import index_artists, is_artist_dnp, update_artist, delete_artist_cache_keys, get_all_artist_post_ids, get_all_artist_flagged_post_ids, get_all_dnp
from ..internals.database.database import get_conn, get_raw_conn, return_conn
from setproctitle import setthreadtitle
from flask import current_app
from os import makedirs
from os.path import join
from bs4 import BeautifulSoup
import datetime
import json
import uuid
import requests
import config
import re
import sys
sys.setrecursionlimit(100000)


def import_posts(import_id, key, contributor_id=None, allowed_to_auto_import=None, key_id=None, offset=1):  # noqa: C901
    setthreadtitle(f'KI{import_id}')
    try:
        scraper = create_scrapper_session().get(
            "https://app.gumroad.com/library",
            cookies={'_gumroad_app_session': key},
            proxies=get_proxy()
        )
        scraper_data = scraper.text
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f'Status code {scraper_data.status_code} when contacting Gumroad API.', 'exception')
        return

    soup = BeautifulSoup(scraper_data, 'html.parser')
    gumroad_data = soup.select_one('[data-react-class=LibraryPage]')
    if not gumroad_data:
        log(import_id, "Can't log in; is your session key correct?")
        if (key_id):
            kill_key(key_id)
        return
    library_data = json.loads(gumroad_data['data-react-props'])

    if (allowed_to_auto_import):
        try:
            encrypt_and_save_session_for_auto_import('gumroad', key, contributor_id=contributor_id)
            log(import_id, "Your key was successfully enrolled in auto-import!", to_client=True)
        except:
            log(import_id, "An error occured while saving your key for auto-import.", 'exception')

    # users = {}
    # for user_info_list in scraper_data['creator_counts'].keys():
    #     parsed_user_info_list = json.loads(user_info_list) # (username, display name, ID), username can be null
    #     users[parsed_user_info_list[1]] = parsed_user_info_list[2]

    dnp = get_all_dnp()
    post_ids_of_users = {}
    flagged_post_ids_of_users = {}
    for product in library_data['results']:
        try:
            post_id = None  # get from data-permalink in element with id download-landing-page on download page
            user_id = product['product']['creator_id']
            cover_url = None
            purchase_download_url = None

            # properties_element = product.find('div', {'data-react-class':'Product/LibraryCard'})
            # react_props = json.loads(properties_element['data-react-props'])
            if not product.get('purchase'):
                log(import_id, f"Skipping post from user {user_id} because it has no purchase data")
                continue
            elif product['purchase']['is_archived']:
                # archived products may contain sensitive data such as a watermark with an e-mail on it
                log(import_id, f"Skipping post from user {user_id} because it is archived")
                continue

            # react_props_product = react_props['product']
            title = product['product']['name']
            # creator_name = product['product']['creator']['name']
            purchase_download_url = product['purchase']['download_url']

            scraper = create_scrapper_session().get(
                purchase_download_url,
                cookies={'_gumroad_app_session': key},
                proxies=get_proxy()
            )
            scraper_data = scraper.text
            scraper_soup = BeautifulSoup(scraper_data, 'html.parser')
            post_id = scraper_soup.select_one('[id=download-landing-page]')['data-permalink']

            if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'gumroad', dnp))) > 0:
                log(import_id, f"Skipping post {post_id} from user {user_id} is in do not post list")
                continue

            # existence checking
            if not post_ids_of_users.get(user_id):
                post_ids_of_users[user_id] = get_all_artist_post_ids('gumroad', user_id)
            if not flagged_post_ids_of_users.get(user_id):
                flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('gumroad', user_id)
            if len(list(filter(lambda post: post['id'] == post_id, post_ids_of_users[user_id]))) > 0 and len(list(filter(lambda flag: flag['id'] == post_id, flagged_post_ids_of_users[user_id]))) == 0:
                log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client=True)
                continue

            log(import_id, f"Starting import: {post_id} from user {user_id}")

            post_model = {
                'id': post_id,
                '"user"': user_id,
                'service': 'gumroad',
                'title': title,
                'content': '',
                'embed': {},
                'shared_file': False,
                'added': datetime.datetime.now(),
                'published': None,
                'edited': None,
                'file': {},
                'attachments': []
            }

            if 'main_cover_id' in product:
                main_cover_id = product['main_cover_id']
                for cover in product['covers']:
                    if cover['id'] == main_cover_id:
                        cover_url = get_value(cover, 'original_url') or cover['url']

            try:
                download_data = json.loads(scraper_soup.select_one('div[data-react-class="DownloadPage/FileList"]')['data-react-props'])
            except:
                download_data = {
                    "content_items": []
                }

            if cover_url:
                reported_filename, hash_filename, _ = download_file(
                    cover_url,
                    'gumroad',
                    user_id,
                    post_id,
                )
                post_model['file']['name'] = reported_filename
                post_model['file']['path'] = hash_filename

            for _file in download_data['content_items']:
                if (_file['type'] == 'file'):
                    reported_filename, hash_filename, _ = download_file(
                        'https://gumroad.com' + _file['download_url'],
                        'gumroad',
                        user_id,
                        post_id,
                        name=f'{_file["file_name"]}.{_file["extension"].lower()}',
                        cookies={'_gumroad_app_session': key}
                    )
                    post_model['attachments'].append({
                        'name': reported_filename,
                        'path': hash_filename
                    })
                else:
                    log(import_id, f"Unsupported content found in product {post_id}. You should tell Shino about this.", to_client=True)
                    log(import_id, json.dumps(_file), to_client=False)
                    continue

            handle_post_import(post_model)
            update_artist('gumroad', user_id)
            delete_post_flags('gumroad', user_id, post_id)

            if (config.ban_url):
                requests.request('BAN', f"{config.ban_url}/{post_model['service']}/user/" + post_model['"user"'])
            delete_artist_cache_keys('gumroad', user_id)

            log(import_id, f"Finished importing post {post_id} from user {user_id}", to_client=False)
        except Exception:
            log(import_id, f"Error while importing {post_id} from user {user_id}", 'exception')
            continue
