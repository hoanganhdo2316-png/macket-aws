"""Apify SDK collector, isolated from Macket web backend."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
VN_TZ = ZoneInfo('Asia/Ho_Chi_Minh')
LOG = logging.getLogger('macket.collector')


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def setup_log() -> None:
    (ROOT / 'logs').mkdir(parents=True, exist_ok=True)
    LOG.setLevel(logging.INFO)
    LOG.handlers.clear()
    formatter = logging.Formatter('%(asctime)s %(levelname)-7s %(message)s')
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(ROOT / 'logs' / 'collector.log', encoding='utf-8')):
        h.setFormatter(formatter)
        LOG.addHandler(h)


def group_id_from_url(url: str) -> str:
    import re
    match = re.search(r'facebook\.com/groups/([^/?#]+)', url)
    return match.group(1).lower() if match else url.rstrip('/').lower()


def value(item: dict, *names: str) -> Any:
    for name in names:
        v = item.get(name)
        if v is not None and v != '':
            return v
    return None


def author_info(item: dict) -> dict:
    user = item.get('user') or item.get('author') or {}
    if not isinstance(user, dict):
        user = {}
    author_id = value(item, 'authorId', 'authorID') or value(user, 'id', 'userId', 'facebookId')
    name = value(item, 'authorName') or value(user, 'name', 'title')
    profile = value(item, 'authorUrl', 'authorProfileUrl') or value(user, 'url', 'profileUrl', 'link')
    return {'id': str(author_id) if author_id is not None else None, 'name': name, 'profile_url': profile}


def images_from(item: dict) -> list[str]:
    found: list[str] = []
    def add(x: Any) -> None:
        if isinstance(x, str) and x.startswith(('https://', 'http://')) and x not in found:
            found.append(x)
        elif isinstance(x, list):
            for i in x:
                add(i)
        elif isinstance(x, dict):
            for key in ('url', 'imageUrl', 'imageURL', 'fullSizeUrl', 'src', 'photoUrl', 'attachments', 'images', 'photos', 'media'):
                if key in x:
                    add(x[key])
    for key in ('imageUrls', 'images', 'photos', 'attachments'):
        add(item.get(key))
    return found


def parse_date(item: dict) -> datetime | None:
    raw = value(item, 'date', 'time', 'createdAt', 'publishTime')
    if raw is None:
        return None
    try:
        if isinstance(raw, (float, int)):
            if raw > 10**12:
                raw = raw / 1000
            return datetime.fromtimestamp(raw, tz=timezone.utc)
        if isinstance(raw, str):
            raw = raw.strip()
            if raw.isdigit():
                return datetime.fromtimestamp(int(raw) / (1000 if len(raw) > 11 else 1), tz=timezone.utc)
            dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return None


def post_key(item: dict) -> str | None:
    postid = value(item, 'postId', 'id', 'legacyId')
    if postid:
        return str(postid)
    url = value(item, 'postUrl', 'url', 'facebookUrl')
    if url and 'facebook.com/' in str(url):
        return 'url:' + str(url).split('?')[0].rstrip('/')
    return None


def normalize(item: dict, group_lookup: dict, now: datetime) -> dict | None:
    key = post_key(item)
    if not key:
        return None
    dt = parse_date(item)
    if dt is None or dt.astimezone(VN_TZ).date() != now.astimezone(VN_TZ).date():
        return None
    group_url = value(item, 'facebookUrl', 'groupUrl', 'inputUrl') or ''
    group_name = value(item, 'groupName', 'groupTitle')
    group = group_lookup.get(group_id_from_url(str(group_url)), {})
    if not group and group_name:
        group = next((g for g in group_lookup.values() if g['name'].casefold() == str(group_name).casefold()), {})
    author = author_info(item)
    return {
        'post_id': key,
        'post_url': value(item, 'postUrl', 'url', 'link'),
        'group_name': group_name or group.get('name'),
        'group_url': group.get('url') or group_url,
        'published_at': dt.astimezone(timezone.utc).isoformat(),
        'published_at_vietnam': dt.astimezone(VN_TZ).isoformat(),
        'author': author,
        'text': value(item, 'text', 'postText', 'message') or '',
        'images': images_from(item),
        'likes_count': value(item, 'likesCount', 'reactionsCount'),
        'comments_count': value(item, 'commentsCount'),
        'shares_count': value(item, 'sharesCount'),
        'collected_at': now.isoformat(),
        'raw': item,
    }


def author_key(author: dict) -> str | None:
    if author.get('id'):
        return 'id:' + str(author['id'])
    if author.get('profile_url'):
        return 'url:' + str(author['profile_url']).split('?')[0].rstrip('/')
    return None  # Names are not unique; do not auto-blacklist on name alone.


def seller_filters(path: Path) -> list[str]:
    data = read_json(path, {'sellers': []})
    if not isinstance(data, dict) or not isinstance(data.get('sellers'), list):
        raise ValueError('blocked_sellers.json must contain {"sellers": [...]}')
    result = []
    for seller in data['sellers']:
        if not isinstance(seller, dict) or seller.get('classification') != 'seller':
            continue
        v = seller.get('id') or seller.get('profile_url') or seller.get('name')
        if isinstance(v, str) and v.strip() and v.strip() not in result:
            result.append(v.strip())
    return result


def is_blocked(author: dict, blocked: list[str]) -> bool:
    # Match ID or profile URL only. Names can collide; use name only on Apify-side
    # when manually configured as a seller without ID (documented risk).
    return any(str(v).strip() in blocked for v in (author.get('id'), author.get('profile_url')) if v)


def connect_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS seen_posts (post_id TEXT PRIMARY KEY, first_seen_utc TEXT NOT NULL)')
    conn.commit()
    return conn


def build_actor_input(groups: list[dict], settings: dict, blocked: list[str]) -> dict:
    return {
        'startUrls': [{'url': g['url']} for g in groups],
        'maxPostsPerGroup': int(settings.get('max_posts_per_group', 3)),
        'sortBy': 'newest',
        'onlyPostsNewerThan': 'today',
        'timeZone': 'Asia/Ho_Chi_Minh',
        'onlyNewPosts': bool(settings.get('only_new_posts', True)),
        'keywords': [], 'excludeKeywords': [],
        'minReactions': 0, 'minComments': 0,
        'excludeAuthors': blocked,
        'skipDuplicates': False,
        'skipPostsWithoutText': False,
        'lightOutput': False,
    }


def collect(api_client: Any, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(VN_TZ)
    groups = read_json(ROOT / 'config' / 'groups.json', [])
    settings = read_json(ROOT / 'config' / 'settings.json', {})
    if not isinstance(groups, list) or not groups:
        raise ValueError('config/groups.json is empty')
    if len(groups) != len({g['url'] for g in groups}):
        raise ValueError('Duplicate group URL in groups.json')
    blocked = seller_filters(ROOT / 'config' / 'blocked_sellers.json')
    actor_input = build_actor_input(groups, settings, blocked)
    max_items = len(groups) * actor_input['maxPostsPerGroup']
    LOG.info('START groups=%d posts_per_group=%d today=%s blocked_sellers=%d only_new=%s',
             len(groups), actor_input['maxPostsPerGroup'], now.strftime('%Y-%m-%d'), len(blocked), actor_input['onlyNewPosts'])
    if dry_run:
        LOG.info('DRY RUN (no charge): actor=%s input=%s', settings.get('actor_id'), json.dumps(actor_input, ensure_ascii=False))
        return {'dry_run': True, 'groups': len(groups), 'actor_input': actor_input}
    if api_client is None:
        raise ValueError('API client is required outside dry-run')
    actor_id = settings.get('actor_id', 'dGw5RQgZjVug05E1h')
    # Call SDK: waits for completion, unlike the 300s synchronous HTTP shortcut.
    run = api_client.actor(actor_id).call(
        run_input=actor_input,
        max_items=max_items,
        max_total_charge_usd=Decimal(str(settings.get('max_total_charge_usd', '0.30'))),
    )
    if not run:
        raise RuntimeError('Apify did not return a completed run')
    run_id = run.get('id')
    status = run.get('status')
    LOG.info('ACTOR run_id=%s status=%s dataset=%s', run_id, status, run.get('defaultDatasetId'))
    if status != 'SUCCEEDED':
        raise RuntimeError(f'Actor run failed or not completed: {status} (run_id={run_id})')
    dataset_id = run.get('defaultDatasetId')
    if not dataset_id:
        raise RuntimeError('Missing defaultDatasetId')
    items = list(api_client.dataset(dataset_id).iterate_items())
    LOG.info('DATASET items=%d', len(items))
    lookup = {group_id_from_url(g['url']): g for g in groups}
    conn = connect_db(ROOT / 'data' / 'seen_posts.sqlite3')
    authors_path = ROOT / 'data' / 'authors_seen.json'
    authors = read_json(authors_path, {})
    if not isinstance(authors, dict):
        raise ValueError('authors_seen.json must be an object')
    accepted = []
    counts = Counter()
    for item in items:
        if not isinstance(item, dict):
            counts['non_post'] += 1
            continue
        record = normalize(item, lookup, now)
        if record is None:
            counts['missing_id_or_outside_today'] += 1
            continue
        author = record['author']
        if is_blocked(author, blocked):
            counts['seller_local_filtered'] += 1
            continue
        key = author_key(author)
        if key:
            old = authors.get(key, {})
            authors[key] = {
                'id': author['id'], 'name': author['name'], 'profile_url': author['profile_url'],
                'classification': old.get('classification', 'unknown'),
                'first_seen': old.get('first_seen', now.isoformat()),
                'last_seen': now.isoformat(),
                'observed_posts': old.get('observed_posts', 0) + 1,
            }
        inserted = conn.execute('INSERT OR IGNORE INTO seen_posts (post_id, first_seen_utc) VALUES (?, ?)',
                                (record['post_id'], datetime.now(timezone.utc).isoformat())).rowcount
        if not inserted:
            counts['duplicate_local'] += 1
            continue
        accepted.append(record)
        counts['accepted'] += 1
        LOG.info('POST id=%s group=%s author=%s author_id=%s date=%s url=%s images=%d',
                 record['post_id'], record['group_name'], author['name'], author['id'],
                 record['published_at_vietnam'], record['post_url'], len(record['images']))
        LOG.info('CONTENT %s', record['text'])
        for index, img in enumerate(record['images'], 1):
            LOG.info('IMAGE %d %s', index, img)
    # Write output before committing seen_posts; failed writes should not mark posts as seen.
    folder = ROOT / 'data' / 'runs'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime('%Y%m%d_%H%M%S_%f')
    out = folder / f'posts_{stamp}.json'
    try:
        write_json(out, accepted)
        write_json(authors_path, authors)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    summary = {
        'run_id': run_id, 'apify_status': status, 'dataset_items': len(items),
        'new_posts': len(accepted), 'counters': dict(counts), 'output': str(out),
    }
    write_json(folder / f'summary_{stamp}.json', summary)
    LOG.info('DONE %s', json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='Macket Apify group collector')
    parser.add_argument('--dry-run', action='store_true', help='Show Actor input without making an API call')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env')
    setup_log()
    try:
        if args.dry_run:
            collect(None, dry_run=True)
        else:
            token = os.getenv('APIFY_TOKEN')
            if not token:
                raise ValueError('Missing APIFY_TOKEN in apify/.env')
            from apify_client import ApifyClient
            collect(ApifyClient(token))
        return 0
    except Exception:
        LOG.exception('Collector failed')
        return 1


if __name__ == '__main__':
    sys.exit(main())
