"""Normalize candidate inputs without resolving or downloading any URL."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit

HEADERS = ['剧名', '视频ID', '热度', '点赞数', '创建时间', '原始链接']


def make_row(id_, url='', local_path=''):
    source = dict.fromkeys(HEADERS, '')
    source.update({'视频ID': id_, '原始链接': url, '剧名': Path(local_path).stem if local_path else '链接素材'})
    return {'video_id': id_, 'url': url, 'local_path': local_path,
            'source': source, 'sheet': '本地视频' if local_path else '粘贴链接', 'row': 1, 'input_error': ''}


def links_to_rows(text):
    rows, seen = [], set()
    for raw in re.findall(r'https?://[^\s<>"，。；！）]+', text):
        url = raw.rstrip('.,;!)]}')
        parsed = urlsplit(url)
        if parsed.hostname not in {'douyin.com', 'www.douyin.com', 'v.douyin.com', 'www.iesdouyin.com'} or parsed.username or parsed.password or parsed.port:
            raise ValueError('仅支持抖音视频链接或抖音分享短链接')
        match = re.fullmatch(r'/video/(\d{1,25})/?', parsed.path)
        if match:
            id_ = match[1]
            url = 'https://www.douyin.com/video/' + id_
        elif parsed.hostname == 'v.douyin.com' and re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path):
            url = 'https://v.douyin.com/' + parsed.path.strip('/') + '/'
            id_ = 'link_' + hashlib.sha256(url.encode()).hexdigest()[:16]
        else:
            raise ValueError('请填写视频详情链接或 v.douyin.com 分享短链接')
        if id_ not in seen:
            rows.append(make_row(id_, url))
            seen.add(id_)
    if not rows:
        raise ValueError('未找到抖音视频链接，可以直接粘贴包含链接的分享文字')
    return rows


def local_files_to_rows(paths):
    rows = []
    for path in dict.fromkeys(str(Path(p).resolve()) for p in paths):
        if not Path(path).is_file():
            raise ValueError('本地视频不存在')
        id_ = 'local_' + hashlib.sha256(path.casefold().encode()).hexdigest()[:16]
        rows.append(make_row(id_, local_path=path))
    return rows
