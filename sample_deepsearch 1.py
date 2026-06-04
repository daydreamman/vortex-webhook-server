import datetime
import json
import os
import requests
from pathlib import Path
from urllib.parse import urlparse

# 帳號密碼與 API 位置
USERNAME = os.getenv('DEEPSEARCH_USERNAME', 'xxx@xxx.vivotek.com')
PASSWORD = os.getenv('DEEPSEARCH_PASSWORD', 'xxxx')
BASE_URL = os.getenv('DEEPSEARCH_BASE_URL', 'https://vortexai.vortexcloud.com/')
DOWNLOAD_DIR = Path(os.getenv('DEEPSEARCH_DOWNLOAD_DIR', '/tmp/deepsearch_samples'))


# 登入取得 JWT token
def login(username, password, base_url):
    url = base_url + 'login'
    res = requests.post(url, json={'username': username, 'password': password}, timeout=60)
    res.raise_for_status()
    data = res.json()
    token = data.get('jwt') or data.get('access_token')
    if not token:
        raise ValueError(f'Unexpected login response: {data}')
    return token


def iter_presigned_urls(obj):
    thumbnail_json = obj.get('thumbnail_json') or {}
    for thumbnails in thumbnail_json.values():
        for thumbnail in thumbnails:
            presigned_url = thumbnail.get('presigned_url')
            if presigned_url:
                yield presigned_url


def download_file(url, destination_dir, object_index, download_index):
    destination_dir.mkdir(parents=True, exist_ok=True)
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        url = f'https://{url.lstrip("/")}'
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    output_path = destination_dir / f'object_{object_index}_thumb_{download_index}.bin'
    output_path.write_bytes(response.content)
    return output_path, len(response.content)


def find_json_range(file_bytes):
    candidate_starts = [index for index, byte in enumerate(file_bytes) if byte in (ord('{'), ord('['))]
    candidate_starts.sort(key=lambda index: (index != 0, index))

    for start in candidate_starts:
        for end in range(len(file_bytes), start, -1):
            if file_bytes[end - 1] not in (ord('}'), ord(']')):
                continue
            try:
                payload = json.loads(file_bytes[start:end].decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            return start, end, payload
    raise ValueError('No valid JSON payload found in downloaded file')


def iter_feature_fields(payload, path='root'):
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_path = f'{path}.{key}'
            if key == 'feature':
                yield next_path, value
            yield from iter_feature_fields(value, next_path)
        return
    if isinstance(payload, list):
        for index, item in enumerate(payload):
            yield from iter_feature_fields(item, f'{path}[{index}]')


def extract_features_from_file(file_path):
    file_bytes = file_path.read_bytes()
    json_start, json_end, payload = find_json_range(file_bytes)
    features = list(iter_feature_fields(payload))
    return json_start, json_end, features


# 呼叫 deepsearch API，從 presigned URL 下載縮圖
def deepsearch_and_download_thumbnails():
    jwt = login(USERNAME, PASSWORD, BASE_URL)
    end_time = datetime.datetime.now(datetime.timezone.utc)
    start_time = end_time - datetime.timedelta(days=1)
    payload = {
        'start': start_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end': end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'mac_list': ['0002D1BC2DEE'],
        'is_asc': False,
        'group_list': [],
        'limit': 5,
        'time_limit': 10,
        'show_debug_info': True,
    }
    url = BASE_URL + 'v1/deepsearch?presigned'
    res = requests.post(
        url,
        json=payload,
        headers={
            'Authorization': f'Bearer {jwt}',
            'Content-Type': 'application/json',
        },
        timeout=60,
    )
    res.raise_for_status()
    data = res.json()['data']
    if not data:
        print('No deepsearch results found.')
        return

    for idx, obj in enumerate(data):
        presigned_urls = list(iter_presigned_urls(obj))
        if not presigned_urls:
            print(f'Object {idx}: no presigned_url in thumbnail_json')
            continue

        for download_index, presigned_url in enumerate(presigned_urls, start=1):
            output_path, file_size = download_file(presigned_url, DOWNLOAD_DIR, idx, download_index)
            print(f'Object {idx}: downloaded thumbnail {download_index} ' f'to {output_path} ({file_size} bytes)')
            json_start, json_end, features = extract_features_from_file(output_path)
            print(f'Object {idx}: json range = [{json_start}, {json_end})')
            if not features:
                print(f'Object {idx}: no feature field found in embedded JSON')
                continue
            for feature_path, feature_values in features:
                preview = feature_values[:5] if isinstance(feature_values, list) else feature_values
                length = len(feature_values) if isinstance(feature_values, list) else 'n/a'
                print(f'Object {idx}: feature path = {feature_path}, ' f'length = {length}, preview = {preview}')


if __name__ == '__main__':
    deepsearch_and_download_thumbnails()
