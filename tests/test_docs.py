from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_relative_documentation_links_exist(self):
        files = [*ROOT.glob('*.md'), *(ROOT / 'docs').glob('*.md')]
        for source in files:
            for target in re.findall(r'(?<!!)\[[^\]]*\]\(([^)\s]+)\)', source.read_text()):
                if '://' in target or target.startswith('mailto:'):
                    continue
                path, _, anchor = target.partition('#')
                destination = source.parent / path if path else source
                with self.subTest(source=source.name, target=target):
                    self.assertTrue(destination.is_file(), f'Missing link: {target}')
                    if anchor and destination.suffix == '.md':
                        headings = re.findall(r'^#+\s+(.+)$', destination.read_text(), re.MULTILINE)
                        slugs = [re.sub(r'\s+', '-', re.sub(r'[^\w\s-]', '', h.lower())) for h in headings]
                        self.assertIn(anchor, slugs)


if __name__ == '__main__':
    unittest.main()
