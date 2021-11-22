from flask import Blueprint, redirect, current_app, make_response, request, app
from src.internals.utils.scrapper import create_scrapper_session
from src.internals.utils.download import download_branding
from src.internals.utils.proxy import get_proxy
import re
import cssutils
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

icons = Blueprint('icons', __name__)

icon_path = join(config.download_path, 'icons')


class ServiceDataType(IntEnum):
    HTML = 1
    JSON = 2


class IconInformationEntry(TypedDict):
    cloudflare: bool
    # @REVIEW: This should be a function which accepts an argument and returns a string.
    # However if the outside code runs `str.format()` on the value, leave it as as,
    # but use kwargs for interpolations at least if it's not out of PR scope
    # @RESPONSE: What do you mean in the last bit about kwargs with str.format()? Don't recall a clean way where that can be done.
    # @REVIEW: `str.format()` accepts kwargs as arguments
    # something like this: "example {key_var}".format(key_var="key_value")
    data_url: str
    data_req_headers: dict
    data_type: ServiceDataType
    # @REVIEW: it isn't referred by this name in initializations
    # @RESPONSE: The `lambda` type doesn't exist...
    # @REVIEW: Not talking about the type, the inits assign the `icon_url` key
    get_icon_url: Callable


@icons.get('/icons/<service>/<user>')
def import_icon(service, user):
    Thread(target=download_icon, args=(service, user)).start()
    response = make_response()
    response.headers['Refresh'] = f'10; url={request.full_path}'
    response.autocorrect_location_header = False
    return response


def get_gumroad_icon_url(data):
    soup = BeautifulSoup(data, 'html.parser')
    sheet = cssutils.css.CSSStyleSheet()
    sheet.add("dummy_selector { %s }" % soup.select_one('.profile-picture-medium.js-profile-picture').get('style'))
    return list(cssutils.getUrls(sheet))[0]


service_icon_information = {
    'patreon': IconInformationEntry(
        cloudflare=True,
        data_url='https://api.patreon.com/user/{}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        icon_url=lambda data: data['included'][0]['attributes']['avatar_photo_url'] if data.get('included') else data['data']['attributes']['image_url']
    ),
    'fanbox': IconInformationEntry(
        cloudflare=False,
        data_url='https://api.fanbox.cc/creator.get?userId={}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        icon_url=lambda data: data['body']['user']['iconUrl']
    ),
    'subscribestar': IconInformationEntry(
        cloudflare=True,
        data_url='https://subscribestar.adult/{}',
        data_req_headers={},
        data_type=ServiceDataType.HTML,
        icon_url=lambda data: BeautifulSoup(data, 'html.parser').find('div', class_='profile_main_info-userpic').contents[0]['src'],
    ),
    'gumroad': IconInformationEntry(
        cloudflare=True,
        data_url='https://gumroad.com/{}',
        data_req_headers={},
        data_type=ServiceDataType.HTML,
        icon_url=get_gumroad_icon_url
    ),
    'fantia': IconInformationEntry(
        cloudflare=False,
        data_url='https://fantia.jp/api/v1/fanclubs/{}',
        data_req_headers={},
        data_type=ServiceDataType.JSON,
        icon_url=lambda data: data['fanclub']['icon']['main']
    )
}


def download_icon(service, user):
    service_data = service_icon_information.get(service)
    # @REVIEW: that's not how `Path`s are initiated
    service_icon_path: Path = join(icon_path, service)
    try:
        if service_data and not exists(join(service_icon_path, user)):
            makedirs(service_icon_path, exist_ok=True)
            scraper = create_scrapper_session(useCloudscraper=service_data['cloudflare']).get(service_data['data_url'].format(user), headers=service_data['data_req_headers'], proxies=get_proxy())
            scraper.raise_for_status()
            data = scraper.json() if service_data['data_type'] == ServiceDataType.JSON else scraper.text
            # @REVIEW: the service path is still joined again
            download_branding(join(config.download_path, 'icons', service), service_data['icon_url'](data), name=user)
    except Exception:
        logging.exception(f'Exception when downloading icon for user {user} on {service}')
        # create an empty file to prevent future requests for the same user if there is an issue.
        with open(join(service_icon_path, user), 'w') as _:
            pass
