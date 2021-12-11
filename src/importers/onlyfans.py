# @REVIEW: This module should be a package which "exports" `import_posts()`
# The structure of the folder is whatever,
# but the minimal structure of the importer should looks like this:
# - a file per table entry, i.e. `posts.py`, `artists.py`, `comments.py` etc.
# these hold funcions responsible for dealing with related entries
# - an `api` file/folder (depending on its size)
# Holds all functions related to requests
# - a `types` file/folder (depending on its size)
# Holds all type-related declarations and static collections
# - optional `lib` file/folder (depending on its size)
# this holds various util and boilerplate functions related to the importer logic
#
# All functions should have their types annotated.
import datetime
import requests
import json
import config
from src.lib.onlyfans import make_headers, get_cookies, create_sign
# @REVIEW: no relative imports beyond the current folder
from ..internals.database.database import get_raw_conn, return_conn
from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.proxy import get_proxy
from ..internals.utils.logger import log
from ..lib.artist import get_all_dnp, get_all_artist_post_ids, get_all_artist_flagged_post_ids, update_artist
from ..lib.post import delete_all_post_cache_keys, delete_post_flags, handle_post_import
from ..internals.utils.download import download_file
from base64 import b64decode, b64encode
from io import StringIO
from html.parser import HTMLParser


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


def import_posts(import_id, key, contributor_id, allowed_to_auto_import, key_id):  # noqa C901
    offset = 0
    # kudos to https://github.com/Amenly/onlyfans-scraper
    key_data = json.loads(b64decode(key.encode('utf8')))
    # @REVIEW: All these side comments will be more fitting
    # as a docstring to a TypedDict declaration.
    auth_data = {
        # @REVIEW: constants should be declared at least in the module scope.
        "app-token": "33d57ade8c02dbc5a333db99ff9ae26a",  # constant
        "sess": key_data['sess'],  # cookie -> sess
        "auth_id": key_data['auth_id'],  # cookie -> auth_id
        "auth_uid_": key_data['auth_uid_'],  # cookie -> auth_uid_; only necessary if 2FA is on
        "user_agent": key_data['user_agent'],  # headers -> user-agent
        "x-bc": key_data['x-bc']  # localStorage -> bcTokenSha, headers -> x-bc
    }
    auth_cookies = get_cookies(auth_data)

    # @REVIEW: why is this a function? its result can be saved in a variable instead.
    def get_auth_headers(url):
        return create_sign(url, make_headers(auth_data))

    # @REVIEW: `scraper_data` gets reassigned in some fucky way.
    # If you really need to reassign it, declare it in the function scope
    # instead of relying on the fact that variables declared in logical scopes
    # also belong to the outer scope in python.
    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            'https://onlyfans.com/api2/v2/posts?limit=10&offset=0&skip_users_dups=1&format=infinite',
            # @REVIEW: no reason to pass `headers` kwarg
            # if you pretty much construct the whole URL
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
                user_id = post['author'].get('username')
                post_id = str(post['id'])

                if not user_id:
                    # Need to investigate why posts can have missing authors like this.
                    # Maybe the process should switch to subscription lists instead of feeds to ensure this doesn't happen?
                    log(import_id, f"Skipping post {post_id} because the author is unknown")
                    continue

                if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'onlyfans', dnp))) > 0:
                    log(import_id, f"Skipping user {user_id} because they are in do not post list", to_client=True)
                    continue

                # existence checking
                # @REVIEW: looks like a candidate for a separate function
                if not post_ids_of_users.get(user_id):
                    post_ids_of_users[user_id] = get_all_artist_post_ids('onlyfans', user_id)
                if not flagged_post_ids_of_users.get(user_id):
                    flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('onlyfans', user_id)

                # @REVIEW: Empty collections get casted to `False` in boolean comparisons
                # so these `len()` calls are entire superfluous.
                # Also `list(filter())` constructs can be replaced with list comprehensions
                # which can also be multilined, unlike lambdas
                if len(list(filter(lambda post: post['id'] == post_id, post_ids_of_users[user_id]))) > 0 and len(list(filter(lambda flag: flag['id'] == post_id, flagged_post_ids_of_users[user_id]))) == 0:
                    log(import_id, f'Skipping post {post_id} from user {user_id} because already exists', to_client=True)
                    continue

                log(import_id, f"Starting import: {post_id} from user {user_id}")

                # @REVIEW: Use `TypedDict` for this dict initialization.
                # And don't mutate it afterwards, so the values for its keys
                # should be figured out beforehand.
                stripped_content = strip_tags(post.get('rawText') or '')
                post_model = {
                    'id': post_id,
                    '"user"': user_id,
                    'service': 'onlyfans',
                    # @REVIEW: this assignment should be calculated beforehand into a separate variable
                    'title': (stripped_content[:60] + '..') if len(stripped_content) > 60 else stripped_content,
                    'content': post.get('rawText') or '',
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
                        if not post_model['file']:
                            reported_filename, hash_filename, _ = download_file(
                                media['full'],
                                'onlyfans',
                                user_id,
                                post_id,
                                cookies=auth_cookies
                            )
                            post_model['file'] = {
                                'name': reported_filename,
                                'path': hash_filename
                            }
                        else:
                            reported_filename, hash_filename, _ = download_file(
                                media['full'],
                                'onlyfans',
                                user_id,
                                post_id,
                                cookies=auth_cookies
                            )
                            post_model['attachments'].append({
                                'name': reported_filename,
                                'path': hash_filename
                            })

                handle_post_import(post_model)
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
            # @REVIEW: this section is not needed, just pass the `offset` variable to the starting request
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
