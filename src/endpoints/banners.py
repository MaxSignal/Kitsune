from flask import Blueprint, redirect, current_app

import requests
import cloudscraper
from os import makedirs
from os.path import exists, join
from bs4 import BeautifulSoup

from configs.env_vars import CONSTANTS
from src.internals.utils.download import download_branding
from src.internals.utils.proxy import get_proxy

banners = Blueprint('banners', __name__)


@banners.route('/banners/<service>/<user>')
def import_banner(service, user):
    makedirs(join(CONSTANTS.DOWNLOAD_PATH, 'banners', service), exist_ok=True)
    if not exists(join(CONSTANTS.DOWNLOAD_PATH, 'banners', service, user)):
        try:
            if service == 'patreon':
                scraper = cloudscraper.create_scraper().get('https://api.patreon.com/user/' + user, proxies=get_proxy())
                data = scraper.json()
                scraper.raise_for_status()
                if data.get('included') and data['included'][0]['attributes'].get('cover_photo_url'):
                    download_branding(
                        join(CONSTANTS.DOWNLOAD_PATH, 'banners', service),
                        data['included'][0]['attributes']['cover_photo_url'],
                        name=user
                    )
                else:
                    raise BannerException()
            elif service == 'fanbox':
                scraper = requests.get('https://api.fanbox.cc/creator.get?userId=' + user, headers={"origin": "https://fanbox.cc"}, proxies=get_proxy())
                data = scraper.json()
                scraper.raise_for_status()
                if data['body']['coverImageUrl']:
                    download_branding(
                        join(CONSTANTS.DOWNLOAD_PATH, 'banners', service),
                        data['body']['coverImageUrl'],
                        name=user
                    )
                else:
                    raise BannerException()
            elif service == 'subscribestar':
                scraper = cloudscraper.create_scraper()
                resp = scraper.get('https://subscribestar.adult/' + user, proxies=get_proxy())
                data = resp.text
                resp.raise_for_status()
                soup = BeautifulSoup(data, 'html.parser')
                if soup.find('img', class_='profile_main_info-cover'):
                    download_branding(
                        join(CONSTANTS.DOWNLOAD_PATH, 'banners', service),
                        soup.find('img', class_='profile_main_info-cover')['src'],
                        name=user
                    )
                else:
                    raise BannerException()
            elif service == 'fantia':
                scraper = requests.get('https://fantia.jp/api/v1/fanclubs/' + user, proxies=get_proxy())
                data = scraper.json()
                scraper.raise_for_status()
                if data['fanclub']['cover']:
                    download_branding(
                        join(CONSTANTS.DOWNLOAD_PATH, 'banners', service),
                        data['fanclub']['cover']['main'],
                        name=user
                    )
                else:
                    raise BannerException()
            else:
                with open(join(CONSTANTS.DOWNLOAD_PATH, 'banners', service, user), 'w') as _:
                    pass
        except BannerException:
            current_app.logger.exception(f'Error importing banner for {user} on {service}')
            with open(join(CONSTANTS.DOWNLOAD_PATH, 'banners', service, user), 'w') as _:
                pass
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                with open(join(CONSTANTS.DOWNLOAD_PATH, 'banners', service, user), 'w') as _:
                    pass
            else:
                current_app.logger.exception(f'HTTP error importing banner for {user} on {service}')

    response = redirect(join('/', 'banners', service, user), code=302)
    response.autocorrect_location_header = False
    return response


class BannerException(Exception):
    pass
