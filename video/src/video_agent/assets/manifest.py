from video_agent.common.io import read_json


def load_asset_manifest(path):
    return read_json(path)
