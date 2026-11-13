from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from spark_omarchy.common import Error, Paths, SCHEMES, OAUTH_DESKTOP
from spark_omarchy.integration import install_integration, uninstall_integration, owned_files
from spark_omarchy.installer import install
from spark_omarchy.cli import uninstall


class IntegrationRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='spark-test-home-')
        self.addCleanup(self.temp.cleanup)
        self.paths = Paths(self.temp.name, {})
        self.paths.data.mkdir(parents=True)
        self.paths.runtime.mkdir()
        (self.paths.data / 'icon.png').write_bytes(b'synthetic icon fixture')
        self.state = {'project': 'spark-omarchy', 'schema': 1, 'prepared': True}
        self.original = {scheme: 'previous.desktop' if i == 0 else ''
                         for i, scheme in enumerate(sorted(SCHEMES))}
        self.handlers = self.original.copy()
        self.calls = []

    def fake_run(self, args, **kwargs):
        # This fake must never invoke the real session bus or alter real defaults.
        args = [str(a) for a in args]
        self.calls.append(args)
        if args[:2] == ['xdg-mime', 'default']:
            self.handlers[args[3].split('/', 1)[1]] = args[2]
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def mock_tools(self):
        first = patch('spark_omarchy.integration.run', side_effect=self.fake_run)
        second = patch('spark_omarchy.integration.query_handler', side_effect=lambda s: self.handlers[s])
        third = patch('spark_omarchy.integration.executable', side_effect=lambda n: '/usr/bin/' + n)
        return first, second, third

    def test_install_repair_uninstall_preserves_original_handler_and_data(self):
        a, b, c = self.mock_tools()
        with a, b, c:
            install_integration(self.paths, self.state)
            self.assertTrue(self.paths.bin.is_file())
            self.assertEqual(self.state['previous_handlers'], self.original)
            self.assertTrue(all(h == OAUTH_DESKTOP for h in self.handlers.values()))
            # Repair is idempotent and must not overwrite previous-handler state.
            install_integration(self.paths, self.state)
            self.assertEqual(self.state['previous_handlers'], self.original)
            self.paths.prefix.mkdir()
            (self.paths.prefix / 'keep-account-data').write_text('synthetic fixture')
            uninstall_integration(self.paths, self.state)
            for scheme, previous in self.original.items():
                if previous:
                    self.assertEqual(self.handlers[scheme], previous)
            self.assertTrue((self.paths.prefix / 'keep-account-data').exists())
            self.assertTrue(self.paths.runtime.exists())
            self.assertTrue(all(not p.exists() for p in owned_files(self.paths)))
            self.assertFalse(self.paths.state()['integrated'])

    def test_later_user_default_is_not_restored_over(self):
        a, b, c = self.mock_tools()
        with a, b, c:
            install_integration(self.paths, self.state)
            scheme = sorted(SCHEMES)[0]
            self.handlers[scheme] = 'new-user-choice.desktop'
            uninstall_integration(self.paths, self.state)
            self.assertEqual(self.handlers[scheme], 'new-user-choice.desktop')

    def test_unrelated_launcher_is_not_clobbered(self):
        self.paths.bin.parent.mkdir(parents=True)
        self.paths.bin.write_text('unrelated file')
        a, b, c = self.mock_tools()
        with a, b, c, self.assertRaises(Error):
            install_integration(self.paths, self.state)
        self.assertEqual(self.paths.bin.read_text(), 'unrelated file')
        self.assertFalse(any(call[:2] == ['xdg-mime', 'default'] for call in self.calls))

    def test_uninstall_never_deletes_arbitrary_state_path(self):
        target = Path(self.temp.name) / 'keep-me'
        target.write_text('unrelated')
        self.state['owned_files'] = [str(target)]
        a, b, c = self.mock_tools()
        with a, b, c, self.assertRaises(Error):
            uninstall_integration(self.paths, self.state)
        self.assertTrue(target.exists())

    def test_prepare_only_purge_allows_an_already_stopped_server(self):
        self.paths.save(self.state)
        self.paths.prefix.mkdir()
        with patch('os.geteuid', return_value=1000), \
             patch('spark_omarchy.cli.run', return_value=SimpleNamespace(returncode=1)), \
             patch('spark_omarchy.cli.prefix_processes', return_value=[]):
            uninstall(self.paths, purge=True, yes=True)
        self.assertFalse(self.paths.data.exists())

    def test_purge_refuses_a_still_running_prefix(self):
        self.paths.save(self.state)
        self.paths.prefix.mkdir()
        with patch('os.geteuid', return_value=1000), \
             patch('spark_omarchy.cli.run', return_value=SimpleNamespace(returncode=1)), \
             patch('spark_omarchy.cli.prefix_processes', return_value=[12345]), \
             self.assertRaises(Error):
            uninstall(self.paths, purge=True, yes=True)
        self.assertTrue(self.paths.prefix.exists())

    def test_uninstall_requires_explicit_confirmation(self):
        self.paths.save(self.state)
        with patch('os.geteuid', return_value=1000), self.assertRaises(Error):
            uninstall(self.paths, purge=True, yes=False)
        self.assertTrue(self.paths.data.exists())

    def test_root_installer_is_refused(self):
        with patch('os.geteuid', return_value=0), self.assertRaises(Error):
            install(self.paths, accept_terms=True)

    def test_terms_are_required_before_changes(self):
        with patch('os.geteuid', return_value=1000), self.assertRaises(Error):
            install(self.paths, accept_terms=False)
        self.assertFalse(self.paths.prefix.exists())


if __name__ == '__main__':
    unittest.main()
