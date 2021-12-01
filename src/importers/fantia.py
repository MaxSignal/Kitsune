import datetime
import json
import sys
from os.path import join
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from setproctitle import setthreadtitle
from configs.env_vars import ENV_VARS
from src.internals.utils.download import DownloaderException, download_file
from src.internals.utils.logger import log
from src.internals.utils.proxy import get_proxy
from src.internals.utils.scrapper import create_scrapper_session

from src.internals.cache.redis import delete_keys
from src.internals.database.database import get_conn, get_raw_conn, return_conn
from src.lib.artist import (
    delete_artist_cache_keys,
    get_all_artist_flagged_post_ids,
    get_all_artist_post_ids,
    get_all_dnp,
    index_artists,
    is_artist_dnp,
    update_artist
)
from src.lib.autoimport import (
    encrypt_and_save_session_for_auto_import,
    kill_key
)
from src.lib.post import (
    delete_backup,
    delete_post_flags,
    handle_post_import,
    move_to_backup,
    post_exists,
    post_flagged,
    restore_from_backup
)

sys.setrecursionlimit(100000)


# In the future, if the timeline API proves itself to be unreliable, we should probably move to scanning fanclubs individually.
# https://fantia.jp/api/v1/me/fanclubs',


def enable_adult_mode(import_id, jar):
    # log(import_id, f"No active Fantia subscriptions or invalid key. No posts will be imported.", to_client = True)
    scraper = create_scrapper_session(useCloudscraper=False).get(
        'https://fantia.jp/mypage/account/edit',
        cookies=jar,
        proxies=get_proxy()
    )
    scraper_data = scraper.text
    scraper.raise_for_status()
    soup = BeautifulSoup(scraper_data, 'html.parser')

    if (soup.select_one('.edit_user input#user_rating') is None):
        log(import_id, "Error while enabling adult mode; key is probably invalid")

    if (soup.select_one('.edit_user input#user_rating').get('checked') is None):
        authenticity_token = soup.select_one('.edit_user input[name=authenticity_token]')['value']
        create_scrapper_session(useCloudscraper=False).post(
            'https://fantia.jp/mypage/users/update_rating',
            cookies=jar,
            proxies=get_proxy(),
            data={
                "utf8": '✓',
                "authenticity_token": authenticity_token,
                "user[rating]": 'adult',
                "commit": '変更を保存'
            }
        ).raise_for_status()
        return True
    return False


def disable_adult_mode(import_id, jar):
    scraper = create_scrapper_session(useCloudscraper=False).get(
        'https://fantia.jp/mypage/account/edit',
        cookies=jar,
        proxies=get_proxy()
    )
    scraper_data = scraper.text
    scraper.raise_for_status()
    soup = BeautifulSoup(scraper_data, 'html.parser')
    authenticity_token = soup.select_one('.edit_user input[name=authenticity_token]')['value']
    create_scrapper_session(useCloudscraper=False).post(
        'https://fantia.jp/mypage/users/update_rating',
        cookies=jar,
        proxies=get_proxy(),
        data={
            "utf8": '✓',
            "authenticity_token": authenticity_token,
            "user[rating]": 'general',
            "commit": '変更を保存'
        }
    ).raise_for_status()


def import_fanclub(fanclub_id, import_id, jar, page=1):  # noqa: C901
    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            f"https://fantia.jp/fanclubs/{fanclub_id}/posts?page={page}",
            cookies=jar,
            proxies=get_proxy()
        )
        scraper_data = scraper.text
        scraper.raise_for_status()
    except requests.HTTPError as exc:
        log(import_id, f'Status code {exc.response.status_code} when contacting Fantia API.', 'exception')
        return

    scraped_posts = BeautifulSoup(scraper_data, 'html.parser').select('div.post')
    user_id = None
    wasFanclubUpdated = False
    dnp = get_all_dnp()
    post_ids_of_users = {}
    flagged_post_ids_of_users = {}
    while True:
        for post in scraped_posts:
            try:
                user_id = fanclub_id
                post_id = post.select_one('a.link-block')['href'].lstrip('/posts/')

                if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'fantia', dnp))) > 0:
                    log(import_id, f"Skipping user {user_id} because they are in do not post list", to_client=True)
                    return

                # existence checking
                if not post_ids_of_users.get(user_id):
                    post_ids_of_users[user_id] = get_all_artist_post_ids('fantia', user_id)
                if not flagged_post_ids_of_users.get(user_id):
                    flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('fantia', user_id)
                if len(list(filter(lambda post: post['id'] == post_id, post_ids_of_users[user_id]))) > 0 and len(list(filter(lambda flag: flag['id'] == post_id, flagged_post_ids_of_users[user_id]))) == 0:
                    log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client=True)
                    continue

                try:
                    post_scraper = create_scrapper_session(useCloudscraper=False).get(
                        f"https://fantia.jp/api/v1/posts/{post_id}",
                        cookies=jar,
                        proxies=get_proxy()
                    )
                    post_data = post_scraper.json()
                    post_scraper.raise_for_status()
                except requests.HTTPError as exc:
                    log(import_id, f'Status code {exc.response.status_code} when contacting Fantia API.', 'exception')
                    continue

                post_model = {
                    'id': post_id,
                    '"user"': user_id,
                    'service': 'fantia',
                    'title': post_data['post']['title'],
                    'content': post_data['post']['comment'] or '',
                    'embed': {},
                    'shared_file': False,
                    'added': datetime.datetime.now(),
                    'published': post_data['post']['posted_at'],
                    'file': {},
                    'attachments': []
                }

                paid_contents = []
                for content in post_data['post']['post_contents']:
                    if content['plan'] and content['plan']['price'] > 0 and content['visible_status'] == 'visible':
                        paid_contents.append(content)
                if (len(paid_contents) == 0):
                    log(import_id, f'Skipping post {post_id} from user {user_id} because no paid contents are unlocked', to_client=True)
                    continue

                log(import_id, f"Starting import: {post_id} from user {user_id}")

                if post_data['post']['thumb']:
                    reported_filename, hash_filename, _ = download_file(
                        post_data['post']['thumb']['original'],
                        'fantia',
                        user_id,
                        post_id,
                    )
                    post_model['file']['name'] = reported_filename
                    post_model['file']['path'] = hash_filename

                for content in post_data['post']['post_contents']:
                    if (content['visible_status'] != 'visible'):
                        continue
                    if content['category'] == 'photo_gallery':
                        for photo in content['post_content_photos']:
                            reported_filename, hash_filename, _ = download_file(
                                photo['url']['original'],
                                'fantia',
                                user_id,
                                post_id,
                                cookies=jar
                            )
                            post_model['attachments'].append({
                                'name': reported_filename,
                                'path': hash_filename
                            })
                    elif content['category'] == 'file':
                        reported_filename, hash_filename, _ = download_file(
                            urljoin('https://fantia.jp/posts', content['download_uri']),
                            'fantia',
                            user_id,
                            post_id,
                            name=content['filename'],
                            cookies=jar
                        )
                        post_model['attachments'].append({
                            'name': reported_filename,
                            'path': hash_filename
                        })
                    elif content['category'] == 'embed':
                        post_model['content'] += f"""
                            <a href="{content['embed_url']}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Embed)</h3>
                                </div>
                            </a>
                            <br>
                        """
                    elif content['category'] == 'blog':
                        for op in json.loads(content['comment'])['ops']:
                            if isinstance(op['insert'], dict) and op['insert'].get('fantiaImage'):
                                reported_filename, hash_filename, _ = download_file(
                                    urljoin('https://fantia.jp/', op['insert']['fantiaImage']['original_url']),
                                    'fantia',
                                    user_id,
                                    post_id,
                                    cookies=jar
                                )
                                post_model['attachments'].append({
                                    'name': reported_filename,
                                    'path': hash_filename
                                })
                    else:
                        log(import_id, f'Skipping content {content["id"]} from post {post_id}; unsupported type "{content["category"]}"', to_client=True)
                        log(import_id, json.dumps(content), to_client=False)

                handle_post_import(post_model)
                delete_post_flags('fantia', user_id, post_id)

                if (ENV_VARS.BAN_URL):
                    requests.request('BAN', f"{ENV_VARS.BAN_URL}/{post_model['service']}/user/" + post_model['"user"'])

                log(import_id, f"Finished importing {post_id} from user {user_id}", to_client=False)
                wasFanclubUpdated = True
            except Exception:
                log(import_id, f'Error importing post {post_id} from user {user_id}', 'exception')

                continue

        if (scraped_posts):
            log(import_id, 'Finished processing page. Processing next page.')
            page = page + 1
            try:
                scraper = create_scrapper_session(useCloudscraper=False).get(
                    f"https://fantia.jp/fanclubs/{fanclub_id}/posts?page={page}",
                    cookies=jar,
                    proxies=get_proxy()
                )
                scraper_data = scraper.text
                scraper.raise_for_status()
                scraped_posts = BeautifulSoup(scraper_data, 'html.parser').select('div.post')
            except requests.HTTPError as exc:
                log(import_id, f'Status code {exc.response.status_code} when contacting Fantia API.', 'exception')
                return
        else:
            delete_artist_cache_keys('fantia', user_id)
            if wasFanclubUpdated:
                update_artist('fantia', user_id)
            return


def get_paid_fanclubs(import_id, jar):
    scraper = create_scrapper_session(useCloudscraper=False).get(
        'https://fantia.jp/mypage/users/plans?type=not_free',
        cookies=jar,
        proxies=get_proxy()
    )
    scraper_data = scraper.text
    scraper.raise_for_status()
    soup = BeautifulSoup(scraper_data, 'html.parser')
    return set(fanclub_link["href"].lstrip("/fanclubs/") for fanclub_link in soup.select("div.mb-5-children > div:nth-of-type(1) a[href^=\"/fanclubs\"]"))


def import_posts(import_id, key, contributor_id, allowed_to_auto_import, key_id):
    setthreadtitle(f'KI{import_id}')
    jar = requests.cookies.RequestsCookieJar()
    jar.set('_session_id', key)

    try:
        mode_switched = enable_adult_mode(import_id, jar)
        fanclub_ids = get_paid_fanclubs(import_id, jar)
    except:
        log(import_id, "Error occurred during preflight. Stopping import.", 'exception')
        if (key_id):
            kill_key(key_id)
        return

    if (allowed_to_auto_import):
        try:
            encrypt_and_save_session_for_auto_import('fantia', jar['_session_id'], contributor_id=contributor_id)
            log(import_id, "Your key was successfully enrolled in auto-import!", to_client=True)
        except:
            log(import_id, "An error occured while saving your key for auto-import.", 'exception')

    if len(fanclub_ids) > 0:
        for fanclub_id in fanclub_ids:
            log(import_id, f'Importing fanclub {fanclub_id}', to_client=True)
            import_fanclub(fanclub_id, import_id, jar)
    else:
        log(import_id, "No paid subscriptions found. No posts will be imported.", to_client=True)

    if (mode_switched):
        disable_adult_mode(import_id, jar)

    log(import_id, "Finished scanning for posts.")
