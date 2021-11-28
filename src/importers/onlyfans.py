import datetime
import requests
import json
import config
from src.lib.onlyfans import make_headers, get_cookies, create_sign
from ..internals.database.database import get_raw_conn, return_conn
from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.proxy import get_proxy
from ..internals.utils.logger import log
from ..lib.artist import get_all_dnp, get_all_artist_post_ids, get_all_artist_flagged_post_ids
from ..lib.post import delete_all_post_cache_keys, delete_post_flags # write_post_to_db, 
from ..internals.utils.download import download_file
from base64 import b64decode, b64encode


def import_posts(import_id, key, contributor_id, allowed_to_auto_import, key_id):
    offset = 0
    # kudos to https://github.com/Amenly/onlyfans-scraper
    key_data = json.loads(b64decode(key.encode('utf8')))
    auth_data = {
        "app-token": "33d57ade8c02dbc5a333db99ff9ae26a",  # constant
        "sess": key_data['sess'],  # cookie -> sess
        "auth_id": key_data['auth_id'],  # cookie -> auth_id
        "auth_uid_": key_data['auth_uid_'],  # cookie -> auth_uid_; only necessary if 2FA is on
        "user_agent": key_data['user_agent'],  # headers -> user-agent
        "x-bc": key_data['x-bc']  # localStorage -> bcTokenSha, headers -> x-bc
    }
    auth_cookies = get_cookies(auth_data)

    def get_auth_headers(url):
        return create_sign(url, make_headers(auth_data))

    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            'https://onlyfans.com/api2/v2/posts?limit=10&offset=0&skip_users_dups=1&format=infinite',
            headers=get_auth_headers('https://onlyfans.com/api2/v2/posts?limit=10&offset=0&skip_users_dups=1&format=infinite'),
            cookies=auth_cookies,
            proxies=get_proxy()
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError as err:
        log(import_id, f'Status code {err.response.status_code} when contacting OnlyFans API.', 'exception')
        return

    dnp = get_all_dnp()
    post_ids_of_users = {}
    flagged_post_ids_of_users = {}
    while True:
        user_id = None
        post_id = None
        for post in scraper_data['list']:
            try:
                if not post['author'].get('username'):
                    log(import_id, f"Skipping post {post_id} because the author is unknown")
                    continue
                
                post_id = str(post['id'])

                if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'onlyfans', dnp))) > 0:
                    log(import_id, f"Skipping user {user_id} because they are in do not post list", to_client=True)
                    return

                # existence checking
                if not post_ids_of_users.get(user_id):
                    post_ids_of_users[user_id] = get_all_artist_post_ids('onlyfans', user_id)
                if not flagged_post_ids_of_users.get(user_id):
                    flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('onlyfans', user_id)
                if len(list(filter(lambda post: post['id'] == post_id, post_ids_of_users[user_id]))) > 0 and len(list(filter(lambda flag: flag['id'] == post_id, flagged_post_ids_of_users[user_id]))) == 0:
                    log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client=True)
                    continue

                log(import_id, f"Starting import: {post_id} from user {user_id}")

                post_model = {
                    'id': post_id,
                    '"user"': user_id,
                    'service': 'onlyfans',
                    'title': (post['rawText'][:60] + '..') if len(post['rawText']) > 60 else post['rawTitle'],
                    'content': post['rawText'],
                    'embed': {},
                    'shared_file': False,
                    'added': datetime.datetime.now(),
                    'published': post['postedAt'],
                    'edited': None,
                    'file': {},
                    'attachments': []
                }

                for media in post['media']:
                    if media['canView']:
                        reported_filename, hash_filename, _ = download_file(
                            media['full'],
                            'onlyfans',
                            user_id,
                            post_id
                        )
                        post_model['attachments'].append({
                            'name': reported_filename,
                            'path': hash_filename
                        })

                post_model['embed'] = json.dumps(post_model['embed'])
                post_model['file'] = json.dumps(post_model['file'])
                for i in range(len(post_model['attachments'])):
                    post_model['attachments'][i] = json.dumps(post_model['attachments'][i])

                columns = post_model.keys()
                data = ['%s'] * len(post_model.values())
                data[-1] = '%s::jsonb[]' # attachments
                query = "INSERT INTO posts ({fields}) VALUES ({values}) ON CONFLICT (id, service) DO UPDATE SET {updates}".format(
                    fields = ','.join(columns),
                    values = ','.join(data),
                    updates = ','.join([f'{column}=EXCLUDED.{column}' for column in columns])
                )
                conn = get_raw_conn()
                try:
                    cursor = conn.cursor()
                    cursor.execute(query, list(post_model.values()))
                    conn.commit()
                finally:
                    return_conn(conn)
                
                update_artist('onlyfans', user_id)
                delete_post_flags('onlyfans', user_id, post_id)

                if (config.ban_url):
                    requests.request('BAN', f"{config.ban_url}/{post_model['service']}/user/" + post_model['"user"'])

                log(import_id, f"Finished importing {post_id} from user {user_id}", to_client=False)
            except Exception:
                log(import_id, f"Error while importing {post_id} from user {user_id}", 'exception')
            continue

        if scraper_data.get('hasMore'):
            offset += 10
            try:
                scraper = create_scrapper_session(useCloudscraper=False).get(
                    f'https://onlyfans.com/api2/v2/posts?limit=10&offset={offset}&skip_users_dups=1&format=infinite',
                    headers=get_auth_headers(f'https://onlyfans.com/api2/v2/posts?limit=10&offset={offset}&skip_users_dups=1&format=infinite'),
                    cookies=auth_cookies,
                    proxies=get_proxy()
                )
                scraper_data = scraper.json()
                scraper.raise_for_status()
            except requests.HTTPError as err:
                log(import_id, f'Status code {err.response.status_code} when contacting OnlyFans API.', 'exception')
                return
        else:
            return
