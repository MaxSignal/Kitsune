import random
import logging

from configs.env_vars import DERIVED_VARS


def get_proxy():
    if DERIVED_VARS.PROXY_LIST:
        proxy = random.choice(DERIVED_VARS.PROXY_LIST)
        return {
            "http": proxy,
            "https": proxy
        }
    else:
        return None
