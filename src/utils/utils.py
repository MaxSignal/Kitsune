import json


def hash_dict(_dict: dict):
    return json.dumps(_dict, sort_keys=True)
