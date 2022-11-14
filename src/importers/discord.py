from ..internals.utils.download import download_file, DownloaderException
from ..lib.post import discord_post_exists
from ..lib.artist import index_discord_channel_server, is_artist_dnp
from ..lib.autoimport import encrypt_and_save_session_for_auto_import, kill_key
from ..internals.database.database import get_conn, get_raw_conn, return_conn
from ..internals.utils.proxy import get_proxy
from ..internals.utils.scrapper import create_scrapper_session
from ..internals.utils.logger import log
from ..internals.cache.redis import delete_keys
from setproctitle import setthreadtitle
import json
import config
from os.path import join, splitext
from random import randrange
import time
import uuid
import requests
import datetime
from random import random
import sys
sys.setrecursionlimit(100000)


userAgent = 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) discord/0.0.269 Chrome/91.0.4472.164 Electron/13.6.6 Safari/537.36'


def test_key_for_auto_import(
    import_id,
    key,
    channel_ids_str,
    contributor_id,
    allowed_to_auto_import,
    key_id
):
    try:
        scraper = create_scrapper_session().get(
            'https://discord.com/api/v9/users/@me',
            headers={'authorization': key, 'user-agent': userAgent},
            proxies=get_proxy()
        )
        scraper.raise_for_status()
    except requests.HTTPError as e:
        if (e.response.status_code == 401):
            if (key_id):
                kill_key(key_id)
        return

    if (allowed_to_auto_import):
        try:
            encrypt_and_save_session_for_auto_import(
                'discord',
                key,
                contributor_id=contributor_id,
                discord_channel_ids=channel_ids_str
            )
            log(import_id, 'Your key was successfully enrolled in auto-import!', to_client=True)
        except:
            log(import_id, 'An error occured while saving your key for auto-import.', 'exception')


def import_channel(channel_id, import_id, key):
    try:
        scraper = create_scrapper_session().get(
            f'https://discord.com/api/v9/channels/{channel_id}',
            headers={'authorization': key, 'user-agent': userAgent},
            proxies=get_proxy()
        )
        channel_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        if(scraper.status_code == 404):
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API. Make sure you entered correct channel id: {channel_id}.", 'exception')
        else:
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    if is_artist_dnp('discord', channel_data['guild_id']):
        log(import_id, f"Skipping channel {channel_id} because server {channel_data['guild_id']} is in do not post list", to_client=True)
        return

    try:
        scraper = create_scrapper_session().get(
            'https://discord.com/api/v9/guilds/' + channel_data['guild_id'],
            headers={'authorization': key, 'user-agent': userAgent},
            proxies=get_proxy()
        )
        server_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        if(scraper.status_code == 404):
            log(
                import_id,
                f"Status code {scraper.status_code} when contacting Discord API."
                "Make sure you entered correct channel id: {channel_id}.",
                'exception'
            )
        else:
            log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return

    # returns true if there were no critical errors
    if process_channel(channel_id, channel_data['guild_id'], import_id, key):
        index_discord_channel_server(channel_data, server_data)


def process_channel(channel_id, server_id, import_id, key, before=None):  # noqa: C901
    log(import_id, f'Starting importing {channel_id}', to_client=True)

    try:
        scraper = create_scrapper_session().get(
            'https://discord.com/api/v9/channels/' +
            channel_id +
            '/messages?limit=50' +
            (('&before=' + before) if before is not None else ''),
            headers={'authorization': key, 'user-agent': userAgent},
            proxies=get_proxy()
        )
        scraper_data = scraper.json()
        scraper.raise_for_status()
    except requests.HTTPError:
        log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
        return False
    except Exception:
        log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
        return False

    while True:
        for post in scraper_data:
            try:
                post_id = post['id']

                if discord_post_exists(server_id, channel_id, post_id):  # todo: post re-importing for discord?
                    log(import_id, f'Skipping post {post_id} from server {server_id} because it already exists', to_client=True)
                    continue

                log(import_id, f"Starting import: {post_id} from server {server_id}")

                post_model = {
                    'id': post_id,
                    'author': post['author'],
                    'server': server_id,
                    'channel': channel_id,
                    'content': post['content'],
                    'added': datetime.datetime.now(),
                    'published': post['timestamp'],
                    'edited': post['edited_timestamp'],
                    'embeds': post['embeds'],
                    'mentions': post['mentions'],
                    'attachments': []
                }

                if('attachments' in post and len(post['attachments']) > 0):
                    for attachment in post['attachments']:
                        filename = attachment['filename']
                        reported_filename, hash_filename, _ = download_file(
                            (
                                attachment['url']
                                if 'url' in attachment and attachment['url'] is not None
                                else attachment['proxy_url']
                            ),
                            None,
                            None,
                            None,
                            name=filename,
                            discord=True,
                            discord_message_server=server_id,
                            discord_message_channel=channel_id,
                            discord_message_id=post_id
                        )
                        post_model['attachments'].append({
                            'name': reported_filename,
                            'path': hash_filename
                        })

                post_model['author'] = json.dumps(post_model['author'])
                for i in range(len(post_model['embeds'])):
                    post_model['embeds'][i] = json.dumps(post_model['embeds'][i])
                for i in range(len(post_model['mentions'])):
                    post_model['mentions'][i] = json.dumps(post_model['mentions'][i])
                for i in range(len(post_model['attachments'])):
                    post_model['attachments'][i] = json.dumps(post_model['attachments'][i])

                columns = post_model.keys()
                data = ['%s'] * len(post_model.values())
                data[-3] = '%s::jsonb[]'  # embeds
                data[-2] = '%s::jsonb[]'  # mentions
                data[-1] = '%s::jsonb[]'  # attachments

                query = "INSERT INTO discord_posts ({fields}) VALUES ({values}) ON CONFLICT (id, server, channel) DO UPDATE SET {updates}".format(
                    fields=','.join(columns),
                    values=','.join(data),
                    updates=','.join([f'{column}=EXCLUDED.{column}' for column in columns])
                )

                conn = get_raw_conn()
                try:
                    cursor = conn.cursor()
                    cursor.execute(query, list(post_model.values()))
                    conn.commit()
                finally:
                    return_conn(conn)

                if (config.ban_url):
                    requests.request('BAN', f"{config.ban_url}/discord/server/{post_model['server']}")
                    requests.request('BAN', f"{config.ban_url}/api/discord/channel/{post_model['channel']}")
                    requests.request('BAN', f"{config.ban_url}/api/discord/channels/lookup?q={post_model['server']}")

                log(import_id, f"Finished importing {post_id} from channel {channel_id}", to_client=False)
            except:
                log(import_id, f"Error while importing {post_id} from channel {channel_id}", 'exception', True)
                continue

        if(len(scraper_data) >= 50):
            time.sleep(randrange(500, 1250) / 1000)
            try:
                before = scraper_data[-1]['id']
                scraper = create_scrapper_session().get(
                    'https://discord.com/api/v9/channels/' +
                    channel_id +
                    '/messages?limit=50' +
                    (('&before=' + before) if before is not None else ''),
                    headers={'authorization': key, 'user-agent': userAgent},
                    proxies=get_proxy()
                )
                scraper_data = scraper.json()
                scraper.raise_for_status()
            except requests.HTTPError:
                log(import_id, f"Status code {scraper.status_code} when contacting Discord API.", 'exception')
                return False
            except Exception:
                log(import_id, 'Error connecting to cloudscraper. Please try again.', 'exception')
                return False
        else:
            log(import_id, "Finished scanning for posts.")
            return True


def import_posts(import_id, key, channel_ids_str, contributor_id, allowed_to_auto_import, key_id):
    setthreadtitle(f'KI{import_id}')
    test_key_for_auto_import(import_id, key, channel_ids_str, contributor_id, allowed_to_auto_import, key_id)
    channel_ids = channel_ids_str.split(',')
    if len(channel_ids) > 0:
        for channel_id in channel_ids:
            log(import_id, f"Importing channel {channel_id}", to_client=True)
            import_channel(channel_id, import_id, key)
    else:
        log(import_id, "No channels has been supplied. No posts will be imported.", to_client=True)
