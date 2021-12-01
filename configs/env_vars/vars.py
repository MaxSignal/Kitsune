import os
from typing import List, Optional

from dotenv import load_dotenv

from .constants import CONSTANTS

# TODO: use it later
env_filename = dict(
    development='.env.dev',
    production='.env.prod'
)

load_dotenv(CONSTANTS.PROJECT_PATH.joinpath('.env'))


class ENV_VARS:
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    SERVER_PORT = os.getenv('WEBSERVER_PORT', '80')
    DATABASE_HOST = os.getenv('DATABASE_HOST', 'localhost')
    DATABASE_DBNAME = os.getenv('DATABASE_DBNAME', 'kemonodb')
    DATABASE_USER = os.getenv('DATABASE_USER', 'nano')
    DATABASE_PASSWORD = os.getenv('DATABASE_PASSWORD', 'shinonome')
    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = os.getenv('REDIS_PORT', '6379')
    PROXIES = os.getenv('PROXIES')
    BAN_URL = os.getenv('BAN_URL')
    PUBKEY = os.getenv('PUBKEY', """
        MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAvEuPOaLW77ymMTMWSzNz
        VqC+/DI7EWI7v3zaLBydH0gVN3FqMlRYOvUYu65K92oM1SYcj2b7sQLbbyEjYLCp
        w3/vc7X5mnFeFghMmN/51ttygV/rmJ8c9TioVOUIphJP6J86AG2MLipUueIZagtf
        2kkzDX544MHbEiJo/LRGjykKtnjMcAH0D4FWZJMPH7P+beI/duLR4pq7bzGOAHEV
        SWTgeHC7MHwoBoMbq03t0R2TjEeShMJKek1dmtiuJ/U0pLdA5wLG2jEcfjI4OZ48
        w10P3DPqRrcH0Q1wHM2zlGEua1LEhPpnUi+xoRXHO1G1m3j3AEXsBZ+JPb7j8c6k
        pQ6IF6VI8dLpBJN5lfKrJXSV8Ui4TZQ0/DPa3z+U+9tekpf3/F2CVhcyMl/nURGo
        UvfNUNtw7MkR+bV1exPIFpLjOVma0yr2FE3/54ZJrsaf7NG0ONdUgtaSCinxldrA
        jMKkn749YzjgtTj4qbsrKMSONUtw+LWXiJvgP4s9v1s03m7BUZ7lWBcBFAXAexOx
        P76veTBuTQWYFoZfAeTRIqKGdW6lWHHVlYyeK7+HBYUQ59uwmp4vZ1nO1yGlefqz
        sVoQGSPVJWdVNVU/rAlyrBVjxJ2ZM54jkdlefd4DRZhLz3JQ6k3PBF40vnL7CYxW
        XxJRiGbXlDkdqYhAgA2AyTcCAwEAAQ==
    """)
    SALT = os.getenv('SALT', '"lolololololololol"')
    PUBSUB = os.getenv('PUBSUB', 'false')
    PUBSUB_QUEUE_LIMIT = os.getenv('PUBSUB_QUEUE_LIMIT', '200')


def validate_vars(var_list: List[Optional[str]]):
    missing_vars = []

    for var in var_list:
        if not getattr(ENV_VARS, var, None):
            missing_vars.append(var)

    if missing_vars:
        var_string = ", ".join(missing_vars)
        raise ValueError(f'These environment variables are not set: {var_string}')


critical_vars = []
validate_vars(critical_vars)
