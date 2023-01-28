from ..internals.utils.proxy import get_proxy
from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.download import download_file, DownloaderException
from ..lib.autoimport import encrypt_and_save_session_for_auto_import, kill_key
from ..lib.post import post_flagged, post_exists, delete_post_flags, move_to_backup, delete_backup, restore_from_backup, handle_post_import
from ..lib.artist import index_artists, is_artist_dnp, update_artist, delete_artist_cache_keys, get_all_artist_post_ids, get_all_artist_flagged_post_ids, get_all_dnp
from ..internals.utils.logger import log
from ..internals.database.database import get_conn, get_raw_conn, return_conn
from ..internals.cache.redis import delete_keys, get_redis
from setproctitle import setthreadtitle
from bs4 import BeautifulSoup
from os.path import join
from urllib.parse import urljoin
import datetime
import json
import config
import requests
import sys
sys.setrecursionlimit(100000)


# In the future, if the timeline API proves itself to be unreliable, we should probably move to scanning fanclubs individually.
# https://fantia.jp/api/v1/me/fanclubs',


def make_safe_request(*args, import_id=None, **kwargs) -> requests.models.Response:
    ''' Makes requests while automatically handling Fantia captchas. '''

    proxies = kwargs.get('proxies', None)
    jar = kwargs.get('cookies', None)
    (url, *_) = args + (None,)

    scraper = create_scrapper_session(useCloudscraper=False)
    response = scraper.get(*args, **kwargs)
    response.raise_for_status()
    data = response.text

    soup = BeautifulSoup(data, 'html.parser')
    if soup.select_one('form#recaptcha_verify'):
        if import_id:
            log(import_id, f'Encountered captcha on URL {url}, solving...')
        authenticity_token = soup.select_one('input[name=authenticity_token]')['value']
        recaptcha_site_key = soup.select_one('input[name=recaptcha_site_key]')['value']
        task = scraper.post('https://api.anti-captcha.com/createTask', data=json.dumps(dict(
            clientKey=config.anticap_token,
            softId=0,
            task=dict(
                type='RecaptchaV3TaskProxyless',
                websiteURL='https://fantia.jp/recaptcha',
                websiteKey=recaptcha_site_key,
                minScore=0.3,
                pageAction='contact',
                isEnterprise=False
            )
        )))
        task_data = task.json()

        recaptcha_response = None
        while recaptcha_response is None:
            task_status = scraper.post(
                'https://api.anti-captcha.com/getTaskResult',
                data=json.dumps(dict(
                    clientKey=config.anticap_token,
                    taskId=task_data['taskId']
                ))
            ).json()
            if task_status['status'] == 'ready':
                recaptcha_response = task_status['solution']['gRecaptchaResponse']
        create_scrapper_session(useCloudscraper=False).post(
            'https://fantia.jp/recaptcha/verify',
            headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
            proxies=proxies,
            cookies=jar,
            data=dict(
                utf8='✓',
                authenticity_token=authenticity_token,
                recaptchaResponse=recaptcha_response,
                commit='ページを表示する'
            )
        ).raise_for_status()
        # Don't loop back if the original URL was to the `/recaptcha` endpoint
        if 'https://fantia.jp/recaptcha' not in url:
            return make_safe_request(*args, **kwargs)
    return response


def enable_adult_mode(import_id, jar, proxies):
    # log(import_id, f"No active Fantia subscriptions or invalid key. No posts will be imported.", to_client = True)
    scraper = make_safe_request(
        'https://fantia.jp/mypage/account/edit',
        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
        import_id=import_id,
        proxies=proxies,
        cookies=jar
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
            headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
            proxies=proxies,
            cookies=jar,
            data={
                "utf8": '✓',
                "authenticity_token": authenticity_token,
                "user[rating]": 'adult',
                "commit": '変更を保存'
            }
        ).raise_for_status()
        return True
    return False


def disable_adult_mode(import_id, jar, proxies):
    scraper = make_safe_request(
        'https://fantia.jp/mypage/account/edit',
        import_id=import_id,
        proxies=proxies,
        cookies=jar
    )
    scraper_data = scraper.text
    scraper.raise_for_status()
    soup = BeautifulSoup(scraper_data, 'html.parser')
    authenticity_token = soup.select_one('.edit_user input[name=authenticity_token]')['value']
    create_scrapper_session(useCloudscraper=False).post(
        'https://fantia.jp/mypage/users/update_rating',
        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
        proxies=proxies,
        cookies=jar,
        data={
            "utf8": '✓',
            "authenticity_token": authenticity_token,
            "user[rating]": 'general',
            "commit": '変更を保存'
        }
    ).raise_for_status()


def import_fanclub(fanclub_id, import_id, jar, proxies, page=1):  # noqa: C901
    try:
        scraper = make_safe_request(
            f"https://fantia.jp/fanclubs/{fanclub_id}/posts?page={page}",
            headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
            import_id=import_id,
            proxies=proxies,
            cookies=jar
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
                    post_page_scraper = create_scrapper_session(useCloudscraper=False).get(
                        f"https://fantia.jp/posts/{post_id}",
                        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                        proxies=proxies,
                        cookies=jar,
                    )
                    post_page_data = post_page_scraper.text
                    post_page_scraper.raise_for_status()
                except requests.HTTPError as exc:
                    log(import_id, f'Status code {exc.response.status_code} when contacting Fantia post page.', 'exception')
                    continue

                soup = BeautifulSoup(post_page_data, 'html.parser')
                csrf_token = soup.select_one('meta[name="csrf-token"]')['content']

                try:
                    post_scraper = create_scrapper_session(useCloudscraper=False).get(
                        f"https://fantia.jp/api/v1/posts/{post_id}",
                        headers={
                            'X-CSRF-Token': csrf_token,
                            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'
                        },
                        proxies=proxies,
                        cookies=jar,
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
                        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                        proxies=proxies
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
                                cookies=jar,
                                headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                                proxies=proxies
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
                            cookies=jar,
                            headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                            proxies=proxies
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
                                    cookies=jar,
                                    headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                                    proxies=proxies
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

                if (config.ban_url):
                    requests.request('BAN', f"{config.ban_url}/{post_model['service']}/user/" + post_model['"user"'])

                log(import_id, f"Finished importing {post_id} from user {user_id}", to_client=False)
                wasFanclubUpdated = True
            except Exception:
                log(import_id, f'Error importing post {post_id} from user {user_id}', 'exception')

                continue

        if (scraped_posts):
            log(import_id, 'Finished processing page. Processing next page.')
            page = page + 1
            try:
                scraper = make_safe_request(
                    f"https://fantia.jp/fanclubs/{fanclub_id}/posts?page={page}",
                    headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
                    import_id=import_id,
                    proxies=proxies,
                    cookies=jar
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


def get_paid_fanclubs(import_id, jar, proxies):
    scraper = make_safe_request(
        'https://fantia.jp/mypage/users/plans?type=not_free',
        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.305 Chrome/69.0.3497.128 Electron/4.0.8 Safari/537.36'},
        import_id=import_id,
        proxies=proxies,
        cookies=jar
    )
    scraper_data = scraper.text
    scraper.raise_for_status()
    soup = BeautifulSoup(scraper_data, 'html.parser')
    return set(fanclub_link["href"].lstrip("/fanclubs/") for fanclub_link in soup.select("div.mb-5-children > div:nth-of-type(1) a[href^=\"/fanclubs\"]"))


def import_posts(import_id, key, contributor_id, allowed_to_auto_import, key_id):  # noqa: C901
    r = get_redis()
    data = json.loads(r.get(f'imports:{import_id}'))

    def update_state(key=None, value=None):
        if key is not None and value is not None:
            data[key] = value
        r.set(f'imports:{import_id}', json.dumps(data, default=str))

    def push_state(key=None, value=None, allow_dupes=False):
        if key is not None and value is not None:
            if value not in data.get(key, []) or allow_dupes:
                data[key] = data.get(key, []) + [value]
        update_state()

    setthreadtitle(f'KI{import_id}')
    jar = requests.cookies.RequestsCookieJar()
    jar.set('_session_id', key)

    proxies = get_proxy()
    if proxies:
        cookies = dict(create_scrapper_session(useCloudscraper=False).head(proxies['http']).cookies)
        proxies['headers'] = {'Cookie': " ".join(f'{k}={v};' for (k, v) in cookies.items())}
    try:
        mode_switched = enable_adult_mode(import_id, jar, proxies)
        fanclub_ids = get_paid_fanclubs(import_id, jar, proxies)
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
            # Push logging data.
            push_state('artists', fanclub_id)
            # Begin importing.
            log(import_id, f'Importing fanclub {fanclub_id}', to_client=True)
            import_fanclub(fanclub_id, import_id, jar, proxies)
    else:
        log(import_id, "No paid subscriptions found. No posts will be imported.", to_client=True)

    if (mode_switched):
        disable_adult_mode(import_id, jar, proxies)

    log(import_id, "Finished scanning for posts.")
