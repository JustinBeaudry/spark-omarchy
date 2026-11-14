import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from spark_omarchy import updater
from spark_omarchy.cli import start, guard_start, update_command
from spark_omarchy.common import Error, Paths, ROOT, NATIVE_UPDATER_CONFIG
from spark_omarchy.integration import update_service_text, update_timer_text
from spark_omarchy.releases import BUNDLE, verify_envelope, validate_catalog


def sha(value):
    return hashlib.sha256(value).hexdigest()


def release(number):
    return {'spark_version': number, 'minimum_client': '0.2.0', 'shim_abi': 1,
            'native_updater_control': 'node-config-v1', 'bundle_relative': BUNDLE,
            'installer_url': f'https://downloads.sparkmailapp.com/Spark3/win/dist/{number}/Spark.exe',
            'installer_sha256': sha(('installer-' + number).encode()),
            'foundation_sha256': sha(b'original fixture'),
            'patched_foundation_sha256': sha(('foundation-' + number).encode()),
            'app_sha256': sha(('exe-' + number).encode()),
            'asar_sha256': sha(('asar-' + number).encode())}


def write_app(path, data):
    path.mkdir(parents=True)
    (path / 'resources').mkdir()
    (path / BUNDLE).mkdir(parents=True)
    number = data['spark_version']
    (path / 'Spark Desktop.exe').write_bytes(('exe-' + number).encode())
    (path / 'resources/app.asar').write_bytes(('asar-' + number).encode())
    (path / BUNDLE / 'Foundation.dll').write_bytes(('foundation-' + number).encode())
    (path / BUNDLE / 'spkenv.dll').write_bytes(b'own shim fixture')


class SigningFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory(prefix='spark-test-signing-')
        cls.private = Path(cls.keys.name) / 'test.key'
        cls.public = Path(cls.keys.name) / 'test-public.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'ED25519', '-out', str(cls.private)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['openssl', 'pkey', '-in', str(cls.private), '-pubout', '-out', str(cls.public)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def catalog(self, selected=None, sequence=1):
        now = datetime.now(timezone.utc)
        selected = release('3.32.5.141587') if selected is None else selected
        return {'schema': 1, 'channel': 'stable', 'sequence': sequence,
                'issued_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'expires_at': (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'recommended': selected['spark_version'], 'releases': [selected]}

    def signed(self, catalog):
        payload = json.dumps(catalog, sort_keys=True, separators=(',', ':')).encode()
        with tempfile.TemporaryDirectory(prefix='spark-test-sign-') as d:
            root = Path(d)
            (root / 'payload').write_bytes(payload)
            subprocess.run(['openssl', 'pkeyutl', '-sign', '-rawin', '-inkey', str(self.private),
                            '-in', str(root / 'payload'), '-out', str(root / 'signature')],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            signature = (root / 'signature').read_bytes()
        return json.dumps({'schema': 1, 'payload': base64.b64encode(payload).decode(),
                           'signature': base64.b64encode(signature).decode()}).encode()

    def verifier(self, data):
        return verify_envelope(data, public_key=self.public)


class SignatureTests(SigningFixture):
    def test_valid_signature(self):
        catalog = self.catalog()
        self.assertEqual(self.verifier(self.signed(catalog)), catalog)

    def test_tampered_payload_rejected(self):
        envelope = json.loads(self.signed(self.catalog()))
        envelope['payload'] = base64.b64encode(b'{"schema":1}').decode()
        with self.assertRaises(Error):
            self.verifier(json.dumps(envelope).encode())

    def test_wrong_key_rejected(self):
        with self.assertRaises(Error):
            verify_envelope(self.signed(self.catalog()), public_key=ROOT / 'trust/updates.pem')

    def test_expired_signed_catalog_rejected(self):
        catalog = self.catalog()
        catalog['issued_at'] = '2020-01-01T00:00:00Z'
        catalog['expires_at'] = '2020-01-02T00:00:00Z'
        with self.assertRaises(Error):
            self.verifier(self.signed(catalog))

    def test_invalid_channel_schema_url_and_layout(self):
        mutations = [lambda c: c.update(schema=True), lambda c: c.update(channel='unreviewed'),
                     lambda c: c['releases'][0].update(installer_url='https://example.org/unknown.exe'),
                     lambda c: c['releases'][0].update(bundle_relative='../../elsewhere'),
                     lambda c: c['releases'][0].update(shim_abi=2),
                     lambda c: c['releases'][0].update(asar_sha256='not a hash')]
        for mutate in mutations:
            catalog = self.catalog()
            mutate(catalog)
            with self.subTest(mutation=mutate), self.assertRaises(Error):
                self.verifier(self.signed(catalog))

    def test_oversized_or_invalid_encoding_rejected(self):
        for data in (b' ' * 262145, b'{}', b'{"schema":1,"payload":"!","signature":"!"}'):
            with self.assertRaises(Error):
                self.verifier(data)

    def test_published_catalog_signature_and_expiry(self):
        catalog = verify_envelope((ROOT / 'updates/stable.json').read_bytes())
        self.assertIn(catalog['recommended'], [r['spark_version'] for r in catalog['releases']])
        self.assertEqual(catalog['channel'], 'stable')


class UpdateTests(SigningFixture):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='spark-update-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.paths = Paths(self.temp.name, {})
        self.paths.data.mkdir(parents=True)
        self.paths.cache.mkdir(parents=True)
        self.old = release('3.32.4.141552')
        self.new = release('3.32.5.141587')
        write_app(self.paths.app_dir, self.old)
        self.mail = self.paths.prefix / 'drive_c/users/test/account-fixture'
        self.mail.parent.mkdir(parents=True)
        self.mail.write_text('synthetic private account fixture; not real mail')
        (self.paths.data / 'icon.png').write_bytes(b'old icon fixture')
        self.state = {'project': 'spark-omarchy', 'schema': 1, 'prepared': True,
                      'integrated': True, 'integration_client_version': '0.2.0',
                      'spark_version': self.old['spark_version'],
                      'release_manifest': self.old, 'shim_sha256': sha(b'own shim fixture')}
        self.paths.save(self.state)
        self.envelope = self.signed(self.catalog(self.new))
        self.verification = patch('spark_omarchy.updater.verify_envelope', side_effect=self.verifier)
        self.verification.start()
        self.addCleanup(self.verification.stop)

    def queue(self):
        source = self.paths.cache / ('Spark-' + self.new['spark_version'] + '.exe')
        source.write_bytes(('installer-' + self.new['spark_version']).encode())
        (self.paths.data / 'pending-update.json').write_bytes(self.envelope)
        return source

    def prepare(self, source, data, shim, stage):
        target = stage / 'app'
        write_app(target, data)
        (stage / 'icon.png').write_bytes(b'new icon fixture')
        return target

    def apply(self):
        self.queue()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare):
            return updater.apply(self.paths, yes=True)

    def test_sequence_replay_and_equivocation_refused(self):
        updater.accept_catalog(self.paths, self.signed(self.catalog(sequence=2)))
        with self.assertRaises(Error):
            updater.accept_catalog(self.paths, self.envelope)
        different = self.catalog(sequence=2)
        different['extra'] = 'different signed content at the same sequence'
        with self.assertRaises(Error):
            updater.accept_catalog(self.paths, self.signed(different))

    def test_minimum_client_required(self):
        data = deepcopy(self.new)
        data['minimum_client'] = '99.0.0'
        with self.assertRaises(Error):
            updater.accept_catalog(self.paths, self.signed(self.catalog(data)))

    def test_background_download_does_not_extract_or_apply_while_running(self):
        source = self.queue()
        with patch('spark_omarchy.updater.fetch_feed', return_value=self.envelope), \
             patch('spark_omarchy.updater.download_installer', return_value=source), \
             patch('spark_omarchy.updater.prefix_processes', return_value=[123]), \
             patch('spark_omarchy.updater.prepare_app') as prepare, \
             patch('spark_omarchy.updater.notify_ready'):
            result = updater.check(self.paths, download=True, background=True)
        self.assertEqual(result['status'], 'downloaded')
        prepare.assert_not_called()
        self.assertFalse(self.paths.app_dir.is_symlink())
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])

    def test_old_integration_must_be_repaired_before_apply(self):
        state = self.paths.state()
        state.pop('integration_client_version')
        self.paths.save(state)
        self.queue()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), self.assertRaisesRegex(Error, 'service guard'):
            updater.apply(self.paths, yes=True)
        self.assertFalse((self.paths.data / 'versions').exists())

    def test_running_prefix_refuses_apply(self):
        self.queue()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[123]), self.assertRaises(Error):
            updater.apply(self.paths, yes=True)
        self.assertFalse((self.paths.data / 'versions').exists())

    def test_confirmation_is_required(self):
        self.queue()
        with patch('os.isatty', return_value=False), self.assertRaises(Error):
            updater.apply(self.paths)

    def test_changed_download_refused(self):
        self.queue().write_bytes(b'tampered')
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), self.assertRaises(Error):
            updater.apply(self.paths, yes=True)
        self.assertFalse(self.paths.app_dir.is_symlink())

    def test_target_bound_to_explicit_confirmation(self):
        self.queue()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), self.assertRaises(Error):
            updater.apply(self.paths, yes=True, expected_version='3.32.6.100')

    def test_success_keeps_data_and_snapshot_and_old_app(self):
        result = self.apply()
        self.assertEqual(result['status'], 'applied')
        self.assertTrue(self.paths.app_dir.is_symlink())
        self.assertEqual(self.mail.read_text(), 'synthetic private account fixture; not real mail')
        backup = self.paths.data / 'backups' / result['backup']
        self.assertEqual((backup / 'prefix/drive_c/users/test/account-fixture').read_text(), self.mail.read_text())
        self.assertFalse((backup / 'prefix/drive_c/SparkOmarchy').exists())
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
        self.assertTrue((self.paths.data / 'versions' / self.old['spark_version'] / 'app').is_dir())
        self.assertFalse(self.paths.state()['last_update']['launched'])
        self.assertFalse((self.paths.data / 'update-transaction.json').exists())

    def test_snapshot_preserves_symlink_without_reading_its_target(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'do-not-copy').write_text('synthetic unrelated fixture')
        link = self.mail.parent / 'external'
        link.symlink_to(outside, target_is_directory=True)
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]):
            identifier = updater.snapshot(self.paths, self.state)
        saved = self.paths.data / 'backups' / identifier / 'prefix/drive_c/users/test/external'
        self.assertTrue(saved.is_symlink())
        self.assertEqual(os.readlink(saved), str(outside))

    def test_pointer_failure_recovers_and_retry_can_reuse_staged_app(self):
        self.queue()
        original = updater.replace_pointer
        count = 0
        def failure(paths, target):
            nonlocal count
            count += 1
            if count == 1:
                raise OSError('synthetic switch failure')
            original(paths, target)
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare), \
             patch('spark_omarchy.updater.replace_pointer', side_effect=failure), self.assertRaises(OSError):
            updater.apply(self.paths, yes=True)
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])
        self.assertTrue(self.paths.app.is_file())
        self.assertFalse((self.paths.data / 'update-transaction.json').exists())
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app') as prepare:
            updater.apply(self.paths, yes=True)
        prepare.assert_not_called()

    def test_process_death_leaves_guarded_journal_and_explicit_recovery(self):
        self.queue()
        def child():
            def crash(paths, target):
                os._exit(99)  # original moved, before atomic pointer replacement
            with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
                 patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare), \
                 patch('spark_omarchy.updater.replace_pointer', side_effect=crash):
                updater.apply(self.paths, yes=True)
        process = multiprocessing.get_context('fork').Process(target=child)
        process.start()
        process.join(15)
        self.assertEqual(process.exitcode, 99)
        self.assertTrue((self.paths.data / 'update-transaction.json').is_file())
        with self.assertRaisesRegex(Error, 'Interrupted update'):
            start(self.paths)
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]):
            self.assertEqual(updater.recover(self.paths)['status'], 'recovered')
        self.assertTrue(self.paths.app.is_file())
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])
        self.assertTrue(self.mail.is_file())

    def test_before_launch_rollback_is_safe_and_post_launch_is_refused(self):
        self.apply()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]):
            self.assertEqual(updater.rollback(self.paths, yes=True)['status'], 'rolled-back')
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])
        self.apply()
        with patch('spark_omarchy.cli.active', return_value=False), \
             patch('spark_omarchy.cli.run', return_value=SimpleNamespace(returncode=0)):
            start(self.paths)
        self.assertTrue(self.paths.state()['last_update']['launched'])
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), self.assertRaises(Error):
            updater.rollback(self.paths, yes=True)
        self.assertEqual(self.paths.state()['spark_version'], self.new['spark_version'])

    def test_background_cli_cannot_apply(self):
        args = SimpleNamespace(check=False, download=True, recover=False, background=True, yes=False)
        with patch('spark_omarchy.cli.updater.check', return_value={'status': 'downloaded'}), \
             patch('spark_omarchy.cli.updater.apply') as apply:
            update_command(self.paths, args)
        apply.assert_not_called()
        args.yes = True
        with self.assertRaises(Error):
            update_command(self.paths, args)

    def test_offline_snapshot_space_failure_does_not_switch(self):
        self.queue()
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare), \
             patch('spark_omarchy.updater.shutil.disk_usage', return_value=SimpleNamespace(free=0)), \
             self.assertRaises(Error):
            updater.apply(self.paths, yes=True)
        self.assertFalse(self.paths.app_dir.is_symlink())
        self.assertFalse((self.paths.data / 'update-transaction.json').exists())
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])
        self.assertFalse((self.paths.data / 'versions' / self.new['spark_version']).exists())

    def test_prestart_guard_marks_direct_systemd_launch_and_refuses_journal(self):
        self.apply()
        guard_start(self.paths)
        self.assertTrue(self.paths.state()['last_update']['launched'])
        (self.paths.data / 'update-transaction.json').write_text('{}')
        with self.assertRaises(Error):
            guard_start(self.paths)

    def test_prestart_refuses_changed_shim(self):
        (self.paths.app_dir / BUNDLE / 'spkenv.dll').write_bytes(b'tampered shim')
        with self.assertRaisesRegex(Error, 'shim changed'):
            guard_start(self.paths)

    def test_state_write_failure_after_pointer_switch_recovers(self):
        self.queue()
        original = self.paths.save
        count = 0
        def fail_once(value):
            nonlocal count
            count += 1
            if count == 1:
                raise OSError('synthetic state-save failure')
            original(value)
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare), \
             patch.object(self.paths, 'save', side_effect=fail_once), self.assertRaises(OSError):
            updater.apply(self.paths, yes=True)
        self.assertEqual(self.paths.state()['spark_version'], self.old['spark_version'])
        self.assertTrue(self.paths.app.is_file())
        self.assertFalse((self.paths.data / 'update-transaction.json').exists())

    def test_initial_migration_metadata_failure_is_retryable(self):
        self.queue()
        original = updater.save_json
        def fail_old_release(path, value):
            if path == self.paths.data / 'versions' / self.old['spark_version'] / 'release.json':
                raise OSError('synthetic migration metadata failure')
            original(path, value)
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]), \
             patch('spark_omarchy.updater.prepare_app', side_effect=self.prepare), \
             patch('spark_omarchy.updater.save_json', side_effect=fail_old_release), self.assertRaises(OSError):
            updater.apply(self.paths, yes=True)
        self.assertFalse((self.paths.data / 'versions' / self.old['spark_version']).exists())
        self.assertTrue(self.paths.app.is_file())
        with patch('spark_omarchy.updater.prefix_processes', return_value=[]):
            self.assertEqual(updater.apply(self.paths, yes=True)['status'], 'applied')

    def test_timer_never_passes_apply_or_yes(self):
        text = update_service_text(self.paths)
        self.assertIn('update --download --background', text)
        self.assertNotIn('--yes', text)
        self.assertNotIn('CPUQuota', text)
        self.assertIn('OnCalendar=daily', update_timer_text())
        self.assertEqual(json.loads(NATIVE_UPDATER_CONFIG), {'features': {'autoUpdaterDisabled': True}})


if __name__ == '__main__':
    unittest.main()
