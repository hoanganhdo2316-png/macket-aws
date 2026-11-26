import pathlib
import tempfile
import unittest
from unittest.mock import patch

from deploy import deploy_web as app
from ci.select_components import components


OLD = 'sha256:' + 'a' * 64
NEW = 'sha256:' + 'b' * 64
FRONT = 'sha256:' + 'c' * 64
BACK_REF = f'{app.REGISTRY}/macket-backend@{OLD}'
FRONT_REF = f'{app.REGISTRY}/macket-frontend@{FRONT}'
SOURCE = f'services:\n  backend-api:\n    image: {BACK_REF}\n  frontend:\n    image: "{FRONT_REF}"\n'


class DeployTests(unittest.TestCase):
    def test_build_selection(self):
        self.assertEqual(components(['backend/main.py']), ['backend'])
        self.assertEqual(components(['frontend/nginx.conf']), ['frontend'])
        self.assertEqual(components(['apify/lambda_trigger.py', 'CONTAINER_DEPLOYMENT.md']), [])
        self.assertEqual(components(['compose.yaml']), ['backend', 'frontend'])

    def test_update_one_image_and_keep_format(self):
        for name, old in [('backend', OLD), ('frontend', FRONT)]:
            before, after, changed = app.replace_image(SOURCE, name, NEW)
            self.assertEqual(changed, SOURCE.replace(old, NEW))
            self.assertEqual(after, before.replace(old, NEW))

    def test_reject_unknown_or_ambiguous_target(self):
        for source, component, digest in [(SOURCE, 'worker', NEW), (SOURCE, 'backend', 'latest'),
                                          (SOURCE * 2, 'backend', NEW)]:
            with self.assertRaises(ValueError):
                app.replace_image(source, component, digest)

    def test_failure_restores_old_manifest_and_recreates_only_target(self):
        def command(args, **kwargs):
            if args[-2:] == ['config', '--services']:
                return 'backend-api\nfrontend'
            if args[:3] == ['docker', 'image', 'inspect']:
                return 'linux/amd64'
            if 'get-caller-identity' in args:
                return 'arn:aws:sts::393840684011:assumed-role/MacketEC2Role/fixture'
            return 'fixture'

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manifest = root / 'compose.yaml'
            manifest.write_text(SOURCE)
            with patch.object(app, 'ROOT', root), patch.object(app, 'MANIFEST', manifest), \
                    patch.object(app.os, 'geteuid', return_value=0, create=True), \
                    patch.object(app, 'host_resources', return_value=(250, 0)), \
                    patch.object(app, 'command', side_effect=command), \
                    patch.object(app, 'smoke'), \
                    patch.object(app, 'container', side_effect=lambda name: ('id', BACK_REF if name == 'backend-api' else FRONT_REF)), \
                    patch.object(app, 'converge', side_effect=[RuntimeError('simulated health failure'), None]) as converge:
                with self.assertRaisesRegex(RuntimeError, 'simulated health failure'):
                    app.deploy('backend', NEW)
                self.assertEqual([call.args[0] for call in converge.call_args_list], ['backend-api', 'backend-api'])
            self.assertEqual(manifest.read_text(), SOURCE)
            backup, = root.glob('compose.before-backend-*')
            self.assertEqual(backup.read_text(), SOURCE)
