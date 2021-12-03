from flask import Blueprint, redirect, current_app, make_response, request, app
from src.internals.utils.scrapper import create_scrapper_session
from src.internals.utils.download import download_branding
from src.internals.utils.proxy import get_proxy
import config
import requests
import cloudscraper
import logging
from os import makedirs
from os.path import exists, join
from bs4 import BeautifulSoup
from pathlib import Path
from enum import IntEnum
from typing import TypedDict, Callable
from threading import Thread

banners = Blueprint('banners', __name__)
banners_path = Path(config.download_path, 'banners')


class ServiceDataType(IntEnum):
    HTML = 1
    JSON = 2


class BannerInformationEntry(TypedDict):
    cloudflare: bool
    data_url: str
    data_req_headers: dict
    data_type: ServiceDataType
    banner_url: Callable


service_banner_information = {
    'patreon': BannerInformationEntry(
        cloudflare=True,
        data_url='https://api.patreon.com/user/{user_id}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        banner_url=lambda data: data['included'][0]['attributes']['cover_photo_url']
    ),
    'fanbox': BannerInformationEntry(
        cloudflare=False,
        data_url='https://api.fanbox.cc/creator.get?userId={user_id}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        banner_url=lambda data: data['body']['coverImageUrl']
    ),
    'subscribestar': BannerInformationEntry(
        cloudflare=True,
        data_url='https://subscribestar.adult/{user_id}',
        data_req_headers={},
        data_type=ServiceDataType.HTML,
        banner_url=lambda data: BeautifulSoup(data, 'html.parser').find('img', class_='profile_main_info-cover')['src'],
    ),
    'fantia': BannerInformationEntry(
        cloudflare=False,
        data_url='https://fantia.jp/api/v1/fanclubs/{user_id}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        banner_url=lambda data: data['fanclub']['cover']['main']
    )
}


def download_banner(service, user):
    service_data = service_banner_information.get(service)
    service_banners_path = Path(banners_path, service)
    user_banners_path = Path(service_banners_path, user)
    try:
        if service_data and not exists(user_banners_path):
            makedirs(service_banners_path, exist_ok=True)
            scraper = create_scrapper_session(useCloudscraper=service_data['cloudflare']).get(service_data['data_url'].format(user_id=user), headers=service_data['data_req_headers'], proxies=get_proxy())
            scraper.raise_for_status()
            data = scraper.json() if service_data['data_type'] == ServiceDataType.JSON else scraper.text
            download_branding(str(service_banners_path), service_data['banner_url'](data), name=user)
    except Exception:
        logging.exception(f'Exception when downloading banner for user {user} on {service}')
        # create an empty file to prevent future requests for the same user if there is an issue.
        with open(user_banners_path, 'w') as _:
            pass


@banners.get('/banners/<service>/<user>')
def import_banner(service, user):
    Thread(target=download_banner, args=(service, user)).start()
    response = make_response()
    response.headers['Refresh'] = f'10; url={request.full_path}'
    response.autocorrect_location_header = False
    return response
