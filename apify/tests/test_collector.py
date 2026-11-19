import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app import collector as c


class FakeDataset:
    def __init__(self, items): self.items = items
    def iterate_items(self): return iter(self.items)


class FakeActor:
    def __init__(self, parent): self.parent = parent
    def call(self, **kwargs):
        self.parent.sent = kwargs
        return {'id': 'run123', 'status': 'SUCCEEDED', 'defaultDatasetId': 'dataset123'}


class FakeClient:
    def __init__(self, items): self.items, self.sent = items, None
    def actor(self, actor_id): return FakeActor(self)
    def dataset(self, dataset_id): return FakeDataset(self.items)


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'config').mkdir()
        c.write_json(self.root / 'config' / 'groups.json', [
            {'name': 'Example', 'url': 'https://www.facebook.com/groups/123/'}])
        c.write_json(self.root / 'config' / 'settings.json', {
            'actor_id': 'dGw5RQgZjVug05E1h', 'max_posts_per_group': 3,
            'only_new_posts': True, 'max_total_charge_usd': '0.30'})
        c.write_json(self.root / 'config' / 'blocked_sellers.json', {'sellers': []})
        self.now = datetime(2026, 11, 17, 12, 0, tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
        self.base = {'postId': 'p1', 'text': 'Máy cá nhân', 'authorId': 'a1',
                     'authorName': 'A', 'date': '2026-11-17T04:00:00Z',
                     'groupName': 'Example', 'postUrl': 'https://facebook.com/groups/123/posts/p1',
                     'imageUrls': ['https://example.org/pic.jpg']}
        self.patch = patch.object(c, 'ROOT', self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_dry_run(self):
        result = c.collect(None, now=self.now, dry_run=True)
        self.assertEqual(result['actor_input']['maxPostsPerGroup'], 3)
        self.assertEqual(result['actor_input']['timeZone'], 'Asia/Ho_Chi_Minh')

    def test_one_post_and_dedup(self):
        client = FakeClient([self.base])
        one = c.collect(client, now=self.now)
        self.assertEqual(one['new_posts'], 1)
        two = c.collect(client, now=self.now)
        self.assertEqual(two['new_posts'], 0)
        self.assertEqual(len(c.read_json(self.root / 'data' / 'authors_seen.json', {})), 1)
        self.assertEqual(client.sent['max_items'], 3)

    def test_seller_filter_only_explicit(self):
        c.write_json(self.root / 'config' / 'blocked_sellers.json', {'sellers': [
            {'id': 'a1', 'classification': 'seller'},
            {'id': 'a2', 'classification': 'individual'},
        ]})
        client = FakeClient([self.base])
        output = c.collect(client, now=self.now)
        self.assertEqual(output['new_posts'], 0)
        self.assertEqual(client.sent['run_input']['excludeAuthors'], ['a1'])

    def test_outside_today(self):
        item = dict(self.base, date='2026-11-16T04:00:00Z')
        self.assertIsNone(c.normalize(item, {'123': {'name': 'Example'}}, self.now))

    def test_unknown_date_is_skipped(self):
        item = dict(self.base)
        item.pop('date')
        self.assertIsNone(c.normalize(item, {}, self.now))


if __name__ == '__main__':
    unittest.main()
