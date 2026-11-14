import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib
from spark_omarchy.cli import callback_arguments, forwarding_command
from spark_omarchy.common import Error, Paths, SCHEMES, atomic_write, manifest
from spark_omarchy.integration import desktop_text, remove_association, service_text, unit_quote
from spark_omarchy.vendor import dib_to_png, patch_foundation


def fixture_pe():
    """Small synthetic PE32+ with exactly the two USERENV imports, not vendor code."""
    b = bytearray(2048)
    b[:2] = b'MZ'
    struct.pack_into('<I', b, 0x3c, 0x80)
    b[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', b, 0x86, 1)
    struct.pack_into('<H', b, 0x94, 240)
    opt = 0x98
    struct.pack_into('<H', b, opt, 0x20b)
    struct.pack_into('<II', b, opt + 120, 0x1000, 40)
    section = opt + 240
    b[section:section + 8] = b'.rdata\0\0'
    struct.pack_into('<IIII', b, section + 8, 1536, 0x1000, 1536, 0x200)
    struct.pack_into('<5I', b, 0x200, 0x1100, 0, 0, 0x1080, 0x1140)
    b[0x280:0x28c] = b'USERENV.dll\0'
    struct.pack_into('<3Q', b, 0x300, 0x1180, 0x11c0, 0)
    for off, name in [(0x380, b'GetProfilesDirectoryW'), (0x3c0, b'GetAllUsersProfileDirectoryW')]:
        b[off:off + 2 + len(name) + 1] = b'\0\0' + name + b'\0'
    return bytes(b)


class CallbackTests(unittest.TestCase):
    def test_registered_schemes(self):
        for scheme in SCHEMES:
            uri = scheme + ':/callback?code=synthetic&state=%2B%22%3B'
            self.assertEqual(callback_arguments(uri), ['--win-open-url', '--', uri])

    def test_invalid_callbacks(self):
        for uri in ('', '--help', 'https://example.org', 'file:///tmp/file',
                    'mailto:example@example.org', 'readdlespark:/unknown',
                    'oauth.redirect.com.readdle.smartmail:/a\nb',
                    'oauth.redirect.com.readdle.smartmail:/a\0b',
                    'oauth.redirect.com.readdle.smartmail:/' + 'x' * 32768):
            with self.subTest(uri=uri[:50]), self.assertRaises(Error):
                callback_arguments(uri)

    @patch('spark_omarchy.cli.executable', side_effect=lambda name: '/usr/bin/' + name)
    def test_forwarding_has_no_shell_or_logging(self, _):
        paths = Paths('/tmp/home space', {})
        uri = next(iter(SCHEMES)) + ':/callback?code=synthetic'
        cmd = forwarding_command(paths, callback_arguments(uri))
        self.assertEqual(cmd[-3:], ['--win-open-url', '--', uri])
        self.assertIn('--slice=spark-omarchy.slice', cmd)
        self.assertIn('--property=StandardOutput=null', cmd)
        self.assertIn('--property=StandardError=null', cmd)
        self.assertNotIn(uri, ' '.join(cmd[:cmd.index('--')]))
        self.assertNotIn('--shell', cmd)


class PathAndIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.paths = Paths('/tmp/test home', {})

    def test_xdg_paths_and_spaces(self):
        self.assertEqual(self.paths.prefix, Path('/tmp/test home/.local/share/spark-omarchy/prefix'))
        self.assertEqual(Paths('/tmp/x', {'XDG_DATA_HOME': '/tmp/custom'}).data,
                         Path('/tmp/custom/spark-omarchy'))

    def test_unsafe_xdg_rejected(self):
        for value in ('relative/path', '/tmp/bad\npath'):
            with self.assertRaises(Error):
                Paths('/tmp/home', {'XDG_DATA_HOME': value})

    def test_no_hard_cap_or_debugging_in_service(self):
        text = service_text(self.paths, '/usr/bin/wine', '/usr/bin/wineserver')
        self.assertNotIn('CPUQuota', text)
        self.assertNotIn('remote-debugging', text)
        self.assertNotIn('Nice=', text)
        self.assertIn('ExecStop=-"/usr/bin/wineserver" -k', text)
        self.assertIn('WINEPREFIX=/tmp/test home/', text)
        self.assertIn('WorkingDirectory=/tmp/test home/', text)
        self.assertNotIn('WorkingDirectory="', text)

    def test_systemd_escaping(self):
        self.assertEqual(unit_quote('a%b$c', arguments=True), '"a%%b$$c"')
        self.assertEqual(unit_quote('a%b$c'), '"a%%b$c"')
        with self.assertRaises(Error):
            unit_quote('path\nExecStart=bad')

    def test_desktop_icon_and_handler(self):
        text = desktop_text(self.paths)
        self.assertIn('Name=Spark Mail\n', text)
        self.assertIn('Icon=spark-omarchy\n', text)
        self.assertIn('"/tmp/test home/.local/bin/spark-omarchy" start', text)
        self.assertNotIn('MimeType=', text)
        bridge = desktop_text(self.paths, True)
        self.assertIn('NoDisplay=true', bridge)
        self.assertIn('open-url %u', bridge)
        self.assertNotIn('x-scheme-handler/https;', bridge)
        self.assertNotIn('mailto', bridge)

    def test_selective_association_rollback(self):
        scheme = 'oauth.redirect.com.readdle.smartmail'
        original = ('# preserve this comment\n[Default Applications]\n'
                    'x-scheme-handler/https=browser.desktop\n'
                    f'x-scheme-handler/{scheme}=new-user-choice.desktop\n'
                    '[Added Associations]\n'
                    f'x-scheme-handler/{scheme}=spark-omarchy-oauth.desktop;other.desktop;\n')
        result = remove_association(original, scheme, 'spark-omarchy-oauth.desktop')
        self.assertIn('# preserve this comment', result)
        self.assertIn('https=browser.desktop', result)
        self.assertIn('=new-user-choice.desktop', result)
        self.assertIn('=other.desktop;', result)
        self.assertNotIn('spark-omarchy-oauth.desktop', result)

    def test_delete_empty_owned_default(self):
        text = '[Default Applications]\nx-scheme-handler/a=spark-omarchy-oauth.desktop\n'
        self.assertEqual(remove_association(text, 'a', 'spark-omarchy-oauth.desktop'), '[Default Applications]\n')

    def test_state_requires_project_marker(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(d, {})
            p.data.mkdir(parents=True)
            p.state_file.write_text('{}')
            with self.assertRaises(Error):
                p.state()
            p.save({'project': 'spark-omarchy', 'schema': 1})
            self.assertEqual(p.state()['schema'], 1)
            self.assertEqual(p.state_file.stat().st_mode & 0o777, 0o600)

    def test_atomic_state_write_persists_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'state.json'
            with patch('spark_omarchy.common.fsync_directory') as sync:
                atomic_write(target, '{}')
            sync.assert_called_once_with(target.parent)
            self.assertEqual(target.read_text(), '{}')

    def test_symlinked_state_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Paths(d, {})
            p.data.mkdir(parents=True)
            target = Path(d) / 'unrelated'
            target.write_text('{}')
            p.state_file.symlink_to(target)
            with self.assertRaises(Error):
                p.state()


class VendorTests(unittest.TestCase):
    def test_manifest_pins_https_vendor_and_checksums(self):
        data = manifest()
        self.assertTrue(data['installer_url'].startswith('https://downloads.sparkmailapp.com/'))
        for key in ('installer_sha256', 'foundation_sha256', 'patched_foundation_sha256'):
            self.assertRegex(data[key], r'^[0-9a-f]{64}$')

    def test_patch_is_guarded_and_same_length(self):
        original = fixture_pe()
        expected = original.replace(b'USERENV.dll\0', b'spkenv.dll\0\0')
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / 'original', Path(d) / 'patched'
            source.write_bytes(original)
            patch_foundation(source, target, hashlib.sha256(original).hexdigest(), hashlib.sha256(expected).hexdigest())
            self.assertEqual(target.read_bytes(), expected)
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(Error):
                patch_foundation(source, source, hashlib.sha256(original).hexdigest(), '')
            with self.assertRaises(Error):
                patch_foundation(source, target, '0' * 64, '')
            with self.assertRaises(Error):
                patch_foundation(source, target, hashlib.sha256(original).hexdigest(), '0' * 64)

    def test_unsupported_import_refused(self):
        original = fixture_pe().replace(b'GetProfilesDirectoryW', b'BadProfilesDirectoryW')
        with tempfile.TemporaryDirectory() as d:
            source, target = Path(d) / 'original', Path(d) / 'patched'
            source.write_bytes(original)
            with self.assertRaises(Error):
                patch_foundation(source, target, hashlib.sha256(original).hexdigest(), '')

    def test_icon_dib_orientation_and_alpha(self):
        # Bottom-up 1x2 BGRA pixels: opaque blue bottom, half-alpha red top.
        header = struct.pack('<IiiHHIIiiII', 40, 1, 4, 1, 32, 0, 8, 0, 0, 0, 0)
        png = dib_to_png(header + bytes([255, 0, 0, 255, 0, 0, 255, 128]) + b'\0' * 8)
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        i = png.index(b'IDAT')
        size = struct.unpack_from('>I', png, i - 4)[0]
        self.assertEqual(zlib.decompress(png[i + 4:i + 4 + size]),
                         bytes([0, 255, 0, 0, 128, 0, 0, 0, 255, 255]))

    def test_icon_unsupported_or_truncated_refused(self):
        for data in (b'', b'\0' * 40, struct.pack('<IiiHHIIiiII', 40, 50000, 4, 1, 32, 0, 0, 0, 0, 0, 0)):
            with self.assertRaises(Error):
                dib_to_png(data)


if __name__ == '__main__':
    unittest.main()
