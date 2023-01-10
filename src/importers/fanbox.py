from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.logger import log
from ..internals.utils.utils import get_import_id
from ..internals.utils.download import download_file, DownloaderException
from ..internals.utils.proxy import get_proxy
from ..lib.autoimport import encrypt_and_save_session_for_auto_import, kill_key
from ..lib.post import post_exists, delete_post_flags, move_to_backup, delete_backup, restore_from_backup, comment_exists, get_comments_for_posts, get_comment_ids_for_user, handle_post_import, get_post
from ..lib.artist import index_artists, is_artist_dnp, update_artist, delete_artist_cache_keys, delete_comment_cache_keys, get_all_artist_post_ids, get_all_artist_flagged_post_ids, get_all_dnp
from ..internals.database.database import get_conn, get_raw_conn, return_conn
from ..internals.cache.redis import delete_keys, get_redis
from flask import current_app
from setproctitle import setthreadtitle
import json
import config
import dateutil
import datetime
import requests
from os.path import join
from os import makedirs
from bs4 import BeautifulSoup

import sys
sys.path.append('./PixivUtil2')
from PixivUtil2.PixivModelFanbox import FanboxArtist, FanboxPost  # noqa: E402


def import_embed(embed, user_id, post_id, import_id):
    embed_id = embed['id']

    log(import_id, f"Starting embed import: {embed_id} from post {post_id}", to_client=False)

    model = {
        'id': embed_id,
        'user_id': user_id,
        'post_id': post_id,
        'type': embed['type'],
        'json': json.dumps(embed)
    }

    columns = model.keys()
    data = ['%s'] * len(model.values())
    query = "INSERT INTO fanbox_embeds ({fields}) VALUES ({values}) ON CONFLICT DO NOTHING".format(
        fields=','.join(columns),
        values=','.join(data)
    )
    conn = get_raw_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(query, list(model.values()))
        conn.commit()
    finally:
        return_conn(conn)


def import_comment(comment, user_id, post_id, import_id):
    commenter_id = comment['user']['userId']
    comment_id = comment['id']

    log(import_id, f"Starting comment import: {comment_id} from post {post_id}", to_client=False)

    post_model = {
        'id': comment_id,
        'post_id': post_id,
        'parent_id': comment['parentCommentId'] if comment['parentCommentId'] != '0' else None,
        'commenter': commenter_id,
        'service': 'fanbox',
        'content': comment['body'],
        'added': datetime.datetime.now(),
        'published': comment['createdDatetime'],
    }

    columns = post_model.keys()
    data = ['%s'] * len(post_model.values())
    query = "INSERT INTO comments ({fields}) VALUES ({values}) ON CONFLICT DO NOTHING".format(
        fields=','.join(columns),
        values=','.join(data)
    )
    conn = get_raw_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(query, list(post_model.values()))
        conn.commit()
    finally:
        return_conn(conn)

    if comment.get('replies'):
        for comment in comment['replies']:
            import_comment(comment, user_id, post_id, import_id)

    if (config.ban_url):
        requests.request('BAN', f"{config.ban_url}/{post_model['service']}/user/" + user_id + '/post/' + post_model['post_id'])
    delete_comment_cache_keys(post_model['service'], user_id, post_model['post_id'])


def import_comments(key, post_id, user_id, import_id, existing_comment_ids, proxies):
    url = f'https://api.fanbox.cc/post.listComments?postId={post_id}&limit=10'

    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://fanbox.cc'},
            proxies=proxies
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f'HTTP error when contacting Fanbox API ({url}). No comments will be imported.', 'exception')
        return

    if scraper_data.get('body'):
        while True:
            for comment in scraper_data['body']['items']:
                comment_id = comment['id']
                try:
                    if len(list(filter(lambda comment: comment['id'] == comment_id, existing_comment_ids))) > 0:
                        log(import_id, f"Skipping comment {comment_id} from post {post_id} because already exists", to_client=False)
                        continue
                    import_comment(comment, user_id, post_id, import_id)
                except Exception:
                    log(import_id, f"Error while importing comment {comment_id} from post {post_id}", 'exception', True)
                    continue

            next_url = scraper_data['body'].get('nextUrl')
            if next_url:
                log(import_id, f"Processing next page of comments for post {post_id}", to_client=False)
                try:
                    scraper = create_scrapper_session(useCloudscraper=False).get(
                        next_url,
                        cookies={'FANBOXSESSID': key},
                        headers={'origin': 'https://fanbox.cc'},
                        proxies=proxies
                    )
                    scraper_data = scraper.json()
                    scraper.raise_for_status()
                except requests.HTTPError:
                    log(import_id, f'HTTP error when contacting Fanbox API ({url}). No comments will be imported.', 'exception')
                    return
            else:
                return

# gets the campaign ids for the creators currently supported


def get_subscribed_ids(import_id, key, proxies, contributor_id=None, allowed_to_auto_import=None, key_id=None, url='https://api.fanbox.cc/post.listSupporting?limit=50'):
    setthreadtitle(f'KI{import_id}')
    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://fanbox.cc'},
            proxies=proxies
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError as e:
        log(import_id, f'HTTP error when contacting Fanbox API ({url}). Stopping import.', 'exception')
        if (e.response.status_code == 401):
            if (key_id):
                kill_key(key_id)
        return set()
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return set()

    user_ids = []
    if scraper_data.get('body'):
        for post in scraper_data['body']['items']:
            user_ids.append(post['user']['userId'])

    campaign_ids = set()
    if len(user_ids) > 0:
        for id in user_ids:
            try:
                if id not in campaign_ids:
                    campaign_ids.add(id)
            except Exception:
                log(import_id, "Error while retrieving one of the campaign ids", 'exception', True)
                continue
    log(import_id, 'Successfully gotten subscriptions')
    return campaign_ids


def download_fancard(key, user_id, import_id, proxies):
    # Download fancards
    fancard_url = 'https://api.fanbox.cc/legacy/support/creator?userId={}'.format(user_id)
    try:
        fancard_scraper = create_scrapper_session(useCloudscraper=False).get(
            fancard_url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://fanbox.cc'},
            proxies=proxies
        )
        fancard_scraper_data = fancard_scraper.json()
        fancard_scraper.raise_for_status()
        download_file(
            fancard_scraper_data['body']['supporterCardImageUrl'],
            None,
            user_id,
            None,
            fancard=True
        )
    except requests.HTTPError as error:
        if error.response.status_code != 404:
            raise
        log(import_id, f'User {user_id} has no fancard', to_client=False)
    except:
        log(import_id, f'Error downloading fancard for user {user_id}', 'exception')


def get_newsletters(import_id, key, proxies, url='https://api.fanbox.cc/newsletter.list'):
    try:
        scraper = create_scrapper_session().get(
            url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://www.fanbox.cc'},
            proxies=proxies
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError as exc:
        log(import_id, f"Status code {exc.response.status_code} when contacting Fanbox API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    if scraper_data.get('body'):
        for newsletter in scraper_data['body']:
            if not newsletter['creator']:
                # The author of the newsletter has been suspended/terminated.
                continue
            newsletter_model = {
                'id': newsletter['id'],
                'user_id': newsletter['creator']['user']['userId'],
                'content': newsletter['body'],
                'published': newsletter['createdAt']
            }

            columns = newsletter_model.keys()
            data = ['%s'] * len(newsletter_model.values())
            query = "INSERT INTO fanbox_newsletters ({fields}) VALUES ({values}) ON CONFLICT DO NOTHING".format(
                fields=','.join(columns),
                values=','.join(data)
            )
            conn = get_raw_conn()
            try:
                cursor = conn.cursor()
                cursor.execute(query, list(newsletter_model.values()))
                conn.commit()
            finally:
                return_conn(conn)


# Retrieve ids of campaigns for which pledge has been cancelled but they've been paid for in this month.
def get_cancelled_ids(import_id, key, proxies, url='https://api.fanbox.cc/payment.listPaid'):
    today_date = datetime.datetime.today()

    try:
        scraper = create_scrapper_session().get(
            url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://fanbox.cc'},
            proxies=proxies
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()

    except requests.HTTPError as exc:
        log(import_id, f"Status code {exc.response.status_code} when contacting Fanbox API.", 'exception')
        return set()
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return set()

    bills = []
    if scraper_data.get('body'):
        for bill in scraper_data['body']:
            try:
                pay_date = dateutil.parser.parse(bill['paymentDatetime'])
                if pay_date.month == today_date.month:
                    bills.append(bill)

            except Exception:
                log(import_id, "Error while parsing one of the bills", 'exception', True)
                continue

    campaign_ids = set()
    if len(bills) > 0:
        for bill in bills:
            try:
                campaign_id = bill['creator']['user']['userId']
                if campaign_id not in campaign_ids:
                    campaign_ids.add(campaign_id)
            except Exception:
                log(import_id, "Error while retrieving one of the cancelled campaign ids", 'exception', True)
                continue

    return campaign_ids

# most of this is copied from the old import_posts.
# now it uses a different url specific to a single creator instead of api.fanbox.cc/post.listSupporting.


def import_posts_via_id(  # noqa: C901
    import_id,
    key,
    campaign_id,
    proxies,
    contributor_id=None,
    allowed_to_auto_import=None,
    key_id=None
):
    url = 'https://api.fanbox.cc/post.listCreator?userId={}&limit=50'.format(campaign_id)
    try:
        scraper = create_scrapper_session(useCloudscraper=False).get(
            url,
            cookies={'FANBOXSESSID': key},
            headers={'origin': 'https://fanbox.cc'},
            proxies=proxies
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError as e:
        log(import_id, f'HTTP error when contacting Fanbox API ({url}). Stopping import.', 'exception')
        if (e.response.status_code == 401):
            if (key_id):
                kill_key(key_id)
        return

    if (allowed_to_auto_import):
        try:
            encrypt_and_save_session_for_auto_import('fanbox', key, contributor_id=contributor_id)
            log(import_id, "Your key was successfully enrolled in auto-import!", to_client=True)
        except:
            log(import_id, "An error occured while saving your key for auto-import.", 'exception')

    # Download fancards
    download_fancard(key, campaign_id, import_id, proxies)

    user_id = None
    wasCampaignUpdated = False
    dnp = get_all_dnp()
    post_ids_of_users = {}
    added_times_of_users = {}
    flagged_post_ids_of_users = {}
    comment_ids_of_users = {}
    if scraper_data.get('body'):
        while True:
            for post in scraper_data['body']['items']:
                user_id = post['user']['userId']
                post_id = post['id']

                url = f'https://api.fanbox.cc/post.info?postId={post_id}'
                try:
                    scraper = create_scrapper_session(useCloudscraper=False).get(
                        url,
                        cookies={'FANBOXSESSID': key},
                        headers={'origin': 'https://fanbox.cc'},
                        proxies=proxies
                    )
                    post = scraper.json()['body']
                    scraper.raise_for_status()
                except requests.HTTPError:
                    log(import_id, f'HTTP error when contacting Fanbox API ({url}). Stopping import.', 'exception')

                parsed_post = FanboxPost(post_id, None, post)
                if parsed_post.is_restricted:
                    log(import_id, f'Skipping post {post_id} from user {user_id} because post is from higher subscription tier')
                    continue
                try:
                    if len(list(filter(lambda artist: artist['id'] == user_id and artist['service'] == 'fanbox', dnp))) > 0:
                        log(import_id, f"Skipping post {post_id} from user {user_id} is in do not post list")
                        continue

                    if not comment_ids_of_users.get(user_id):
                        comment_ids_of_users[user_id] = get_comment_ids_for_user('fanbox', user_id)
                    import_comments(
                        key, post_id, user_id, import_id,
                        comment_ids_of_users[user_id],
                        proxies
                    )

                    # existence checking
                    if post_ids_of_users.get(user_id) is None or not added_times_of_users.get(user_id) is None:
                        added_times_of_users[user_id] = {}
                        post_ids_of_users[user_id] = []
                        for artist_post in get_all_artist_post_ids('fanbox', user_id, ['id', 'added']):
                            added_times_of_users[user_id][artist_post['id']] = artist_post['added']
                            post_ids_of_users[user_id] += [artist_post['id']]
                    if not flagged_post_ids_of_users.get(user_id):
                        flagged_post_ids_of_users[user_id] = get_all_artist_flagged_post_ids('fanbox', user_id)
                    # A post is already present in the database. Should it be skipped?
                    if list(filter(lambda _post_id: _post_id == post_id, post_ids_of_users[user_id])):
                        post_flagged = list(filter(
                            lambda flag: flag['id'] == post_id,
                            flagged_post_ids_of_users[user_id]
                        ))
                        existing_post_added_time = added_times_of_users[user_id][post_id].timestamp()
                        post_updated = parsed_post.updatedDateDatetime.timestamp() > existing_post_added_time
                        if not post_flagged and not post_updated:
                            log(
                                import_id,
                                f'Skipping post {post_id} from user {user_id} because already exists',
                                to_client=True
                            )
                            continue

                    log(import_id, f"Starting import: {post_id} from user {user_id}")

                    post_model = {
                        'id': post_id,
                        '"user"': user_id,
                        'service': 'fanbox',
                        'title': post['title'],
                        'content': parsed_post.body_text,
                        'embed': {},
                        'shared_file': False,
                        'added': datetime.datetime.now(),
                        'published': post['publishedDatetime'],
                        'edited': post['updatedDatetime'],
                        'file': {},
                        'attachments': []
                    }

                    service_provider_handlers = {
                        'twitter': """
                            <a href="https://twitter.com/_/status/{content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Twitter)</h3>
                                </div>
                            </a>
                            <br>
                        """,
                        'youtube': """
                            <a href="https://www.youtube.com/watch?v={content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(YouTube)</h3>
                                </div>
                            </a>
                            <br>
                        """,
                        'fanbox': """
                            <a href="https://www.pixiv.net/fanbox/{content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Fanbox)</h3>
                                </div>
                            </a>
                            <br>
                        """,
                        'vimeo': """
                            <a href="https://vimeo.com/{content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Vimeo)</h3>
                                </div>
                            </a>
                            <br>
                        """,
                        'google_forms': """
                            <a href="https://docs.google.com/forms/d/e/{content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Google Forms)</h3>
                                </div>
                            </a>
                            <br>
                        """,
                        'soundcloud': """
                            <a href="https://soundcloud.com/{content_id}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(Soundcloud)</h3>
                                </div>
                            </a>
                            <br>
                        """
                    }

                    if post['body'].get('urlEmbedMap'):
                        for embed in post['body']['urlEmbedMap'].values():
                            import_embed(embed, user_id, post_id, import_id)

                    for i in range(len(parsed_post.embeddedFiles)):
                        if isinstance(parsed_post.embeddedFiles[i], dict):
                            service_provider_handler = service_provider_handlers.get(parsed_post.embeddedFiles[i]['serviceProvider'])
                            if (service_provider_handler):
                                post_model['content'] += service_provider_handler.format(content_id=parsed_post.embeddedFiles[i]['serviceProvider'])
                            else:
                                log(import_id, f'Unexpected service provider "{parsed_post.embeddedFiles[i]["serviceProvider"]}" found in post {post_id}. Skipping...')
                                continue
                        elif isinstance(parsed_post.embeddedFiles[i], str):
                            if i == 0:
                                reported_filename, hash_filename, _ = download_file(
                                    parsed_post.embeddedFiles[i],
                                    'fanbox',
                                    user_id,
                                    post_id,
                                    cookies={'FANBOXSESSID': key},
                                    headers={'origin': 'https://fanbox.cc'}
                                )
                                post_model['file']['name'] = reported_filename
                                post_model['file']['path'] = hash_filename
                            else:
                                reported_filename, hash_filename, _ = download_file(
                                    parsed_post.embeddedFiles[i],
                                    'fanbox',
                                    user_id,
                                    post_id,
                                    cookies={'FANBOXSESSID': key},
                                    headers={'origin': 'https://fanbox.cc'}
                                )
                                post_model['attachments'].append({
                                    'name': reported_filename,
                                    'path': hash_filename
                                })

                    soup = BeautifulSoup(post_model['content'], 'html.parser')
                    for iframe in soup.select('iframe[src^="https://cdn.iframe.ly/"]'):
                        api_url = iframe['src'].split('?', maxsplit=1)[0] + '.json'
                        api_response = create_scrapper_session(useCloudscraper=False).get(api_url, proxies=proxies)
                        api_data = api_response.json()
                        iframe.parent.parent.replace_with(BeautifulSoup(f"""
                            <a href="{api_data['url']}" target="_blank">
                                <div class="embed-view">
                                  <h3 class="subtitle">(frame embed)</h3>
                                </div>
                            </a>
                            <br>
                        """, 'html.parser'))
                        post_model['content'] = str(soup)

                    handle_post_import(post_model)
                    delete_post_flags('fanbox', user_id, post_id)

                    if (config.ban_url):
                        requests.request('BAN', f"{config.ban_url}/{post_model['service']}/user/" + post_model['"user"'])

                    log(import_id, f'Finished importing {post_id} for user {user_id}', to_client=False)
                    wasCampaignUpdated = True
                except Exception:
                    log(import_id, f'Error importing post {post_id} from user {user_id}', 'exception')
                    continue

            if scraper_data['body'].get('nextUrl'):
                url = scraper_data['body'].get('nextUrl')
                try:
                    scraper = create_scrapper_session().get(
                        url,
                        cookies={'FANBOXSESSID': key},
                        headers={'origin': 'https://fanbox.cc'},
                        proxies=proxies
                    )
                    scraper_data = scraper.json()
                    scraper.raise_for_status()
                except requests.HTTPError as err:
                    log(import_id, f'HTTP error when contacting Fanbox API ({url}, {err.response.status_code}). Stopping import.', 'exception')
                    return
            else:
                delete_artist_cache_keys('fanbox', user_id)
                if wasCampaignUpdated:
                    update_artist('fanbox', user_id)
                return
    else:
        log(import_id, 'No posts detected.')


def import_posts(import_id, key, contributor_id=None, allowed_to_auto_import=None, key_id=None):
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

    proxies = get_proxy()
    if proxies:
        cookies = dict(create_scrapper_session(useCloudscraper=False).head(proxies['http']).cookies)
        proxies['headers'] = {'Cookie': " ".join(f'{k}={v};' for (k, v) in cookies.items())}

    get_newsletters(import_id, key, proxies)
    # this block creates a list of campaign ids of both supported and canceled subscriptions within the month
    subscribed_ids = get_subscribed_ids(import_id, key, proxies)
    cancelled_ids = get_cancelled_ids(import_id, key, proxies)
    ids = set()
    if len(subscribed_ids) > 0:
        ids.update(subscribed_ids)
    if len(cancelled_ids) > 0:
        ids.update(cancelled_ids)
    campaign_ids = list(ids)

    # this block uses the list of ids to import posts
    if len(campaign_ids) > 0:
        for campaign_id in campaign_ids:
            # Push logging data.
            push_state('artists', campaign_id)
            # Begin importing.
            import_posts_via_id(
                import_id, key, campaign_id, proxies,
                contributor_id=contributor_id,
                allowed_to_auto_import=allowed_to_auto_import,
                key_id=key_id
            )
            log(import_id, f'Finished processing user {campaign_id}')
        log(import_id, 'Finished scanning for posts')
    else:
        log(import_id, "No active subscriptions or invalid key. No posts will be imported.", to_client=True)
