import datetime
import json
import os
import sys
import uuid
from html.parser import HTMLParser
from io import StringIO
from os.path import join
from urllib.parse import urlparse

import dateparser
import requests
from bs4 import BeautifulSoup
from flask import current_app
from setproctitle import setthreadtitle
from configs.env_vars import ENV_VARS
from src.internals.utils.download import DownloaderException, download_file
from src.internals.utils.logger import log
from src.internals.utils.proxy import get_proxy
from src.internals.utils.scrapper import create_scrapper_session
from src.internals.utils.utils import parse_date

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
    move_to_backup,
    post_exists,
    post_flagged,
    restore_from_backup
)


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, d):
        self.text.write(d)

    def get_data(self):
        return self.text.getvalue()


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


def import_posts(import_id, key, contributor_id, allowed_to_auto_import, key_id):  # noqa C301
    setthreadtitle(f'KI{import_id}')

    jar = requests.cookies.RequestsCookieJar()
    jar.set('auth_token', key)
    try:
        scraper = create_scrapper_session(useCloudscraper=True).get(
            "https://subscribestar.adult/phd14517a.json",
            cookies=jar,
            proxies=get_proxy()
        )
        scraper_data = scraper.json()['html']
        scraper.raise_for_status()
    except requests.HTTPError as exc:
        log(import_id, f'Status code {exc.response.status_code} when contacting SubscribeStar API.', 'exception')
        return

    if scraper_data == "":
        log(import_id, "No active subscriptions or invalid key. No posts will be imported.")
        return  # break early as there's nothing anyway

    first_run = True
    dnp = get_all_dnp()
    post_ids_of_users = {}
    flagged_post_ids_of_users = {}
    while True:
        soup = BeautifulSoup(scraper_data, 'html.parser')
        posts = soup.find_all("div", {"class": "post"})
        if (first_run and len(posts) == 0):
            if (key_id):
                kill_key(key_id)
        else:
            if (allowed_to_auto_import):
                try:
                    encrypt_and_save_session_for_auto_import('subscribestar', key, contributor_id=contributor_id)
                    log(import_id, "Your key was successfully enrolled in auto-import!", to_client=True)
                except:
                    log(import_id, "An error occured while saving your key for auto-import.", 'exception')

        first_run = False
        for post in posts:
            try:
                post_id = post['data-id']
                user_id = post.find("a", {"class": "post-avatar"})['href'].replace('/', '')

                if "is-locked" in post.find("div", {"class": "post-body"})['class']:
                    log(import_id, f"Skipping post {post_id} from user {user_id} as tier is too high")
                    continue

                if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'subscribestar', dnp))) > 0:
                    log(import_id, f"Skipping post {post_id} from user {user_id} is in do not post list")
                    continue

                # existence checking
                if not post_ids_of_users.get(user_id):
                    post_ids_of_users[user_id] = get_all_artist_post_ids('subscribestar', user_id)
                if not flagged_post_ids_of_users.get(user_id):
                    flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('subscribestar', user_id)
                if len(list(filter(lambda post: post['id'] == post_id, post_ids_of_users[user_id]))) > 0 and len(list(filter(lambda flag: flag['id'] == post_id, flagged_post_ids_of_users[user_id]))) == 0:
                    log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client=True)
                    continue

                log(import_id, f"Starting import: {post_id}")
                # post_data = post.find("div", {"class": "trix-content"})
                post_data = post.find("div", {"class": "post-content"})
                # content = ""
                # for elem in post_data.recursiveChildGenerator():
                #     if isinstance(elem, str):
                #         content += elem.strip()
                #     elif elem.name == 'br':
                #         content += '\n'

                stripped_content = strip_tags(post_data.text)
                date = post.find("div", {"class": "post-date"}).a.get_text()
                parsed_date = dateparser.parse(date.replace("DOPOLEDNE", "AM").replace("ODPOLEDNE", "PM"))  # Workaround for the Czeck langage

                post_model = {
                    'id': str(post_id),
                    '"user"': user_id,
                    'service': 'subscribestar',
                    'title': (stripped_content[:60] + '..') if len(stripped_content) > 60 else stripped_content,
                    'content': str(post_data),
                    'embed': {},
                    'shared_file': False,
                    'added': datetime.datetime.now(),
                    'published': parsed_date,
                    'edited': None,
                    'file': {},
                    'attachments': []
                }

                post_attachment_field = post.find("div", {"class": "uploads"})
                if post_attachment_field:  # if posts has any kind of attachement
                    image_attachments = post_attachment_field.find("div", {"class": "uploads-images"})
                    docs_attachments = post_attachment_field.find("div", {"class": "uploads-docs"})

                    if image_attachments:
                        for attachment in json.loads(image_attachments['data-gallery']):
                            name = os.path.basename(urlparse(attachment['url']).path)  # gets the filename from the url
                            # download the file
                            reported_filename, hash_filename, _ = download_file(
                                attachment['url'],
                                'subscribestar',
                                user_id,
                                str(post_id),
                                name=name
                            )
                            # add it to the list
                            post_model['attachments'].append({
                                'name': reported_filename,
                                'path': hash_filename
                            })

                    if docs_attachments:
                        for attachment in docs_attachments.children:
                            name = os.path.basename(urlparse(attachment.div.a['href']).path)  # gets the filename from the url
                            # download the file
                            reported_filename, hash_filename, = download_file(
                                attachment.div.a['href'],
                                'subscribestar',
                                user_id,
                                str(post_id),
                                name=name
                            )
                            # add it to the list
                            post_model['attachments'].append({
                                'name': reported_filename,
                                'path': hash_filename
                            })

                post_model['attachments'] = [json.dumps(attach) for attach in post_model['attachments']]

                # add the post to DB
                post_model['embed'] = json.dumps(post_model['embed'])
                post_model['file'] = json.dumps(post_model['file'])

                columns = post_model.keys()
                data = ['%s'] * len(post_model.values())
                data[-1] = '%s::jsonb[]'  # attachments
                query = "INSERT INTO posts ({fields}) VALUES ({values}) ON CONFLICT (id, service) DO UPDATE SET {updates}".format(
                    fields=','.join(columns),
                    values=','.join(data),
                    updates=','.join([f'{column}=EXCLUDED.{column}' for column in columns])
                )
                conn = get_raw_conn()
                try:
                    cursor3 = conn.cursor()
                    cursor3.execute(query, list(post_model.values()))
                    conn.commit()
                finally:
                    return_conn(conn)

                update_artist('subscribestar', user_id)
                delete_post_flags('subscribestar', user_id, str(post_id))

                if (ENV_VARS.BAN_URL):
                    requests.request('BAN', f"{ENV_VARS.BAN_URL}/{post_model['service']}/user/" + post_model['"user"'])
                delete_artist_cache_keys('subscribestar', user_id)

                log(import_id, f"Finished importing {post_id} from user {user_id}", to_client=False)

            except Exception:
                log(import_id, f"Error while importing {post_id} from user {user_id}", 'exception')
                continue

        more = soup.find("div", {"class": "posts-more"})

        if more:  # we get the next HTML ready, and it'll process the new
            try:
                scraper = create_scrapper_session(useCloudscraper=True).get(
                    "https://www.subscribestar.com" + more['href'],  # the next page
                    cookies=jar,
                    proxies=get_proxy()
                )
                scraper_data = scraper.json()['html']
                scraper.raise_for_status()
            except requests.HTTPError as exc:
                log(import_id, f'Status code {exc.response.status_code} when contacting SubscribeStar API.', 'exception')
                return

        else:  # We got all the posts, exit
            log(import_id, "Finished scanning for posts.")
            return
