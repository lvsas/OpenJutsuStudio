"""Bounded presentation guards, not GPU, publication or media-rights acceptance.

Normal execution checks files in the working tree. After staging documentation and
assets, maintainers must also set OPENGENJUTSU_JURY_REQUIRE_TRACKED=1. That separate
gate checks Git's index without modifying it. No network or app process is used.
"""
from __future__ import annotations

import ast
from html.parser import HTMLParser
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PAGES = (
    "README.md", "docs/jury-guide.md", "docs/release-readiness.md",
    "docs/local-setup.md", "docs/executor-setup.md",
)


def without_code(text):
    return re.sub(r"^(`{3,}|~{3,}).*?^\1[^\n]*$", "", text,
                  flags=re.MULTILINE | re.DOTALL)


class HTMLLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.anchors = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.anchors.add(attrs["id"])
        if tag == "a" and "name" in attrs:
            self.anchors.add(attrs["name"])
        key = "src" if tag == "img" else "href" if tag == "a" else None
        if key and key in attrs:
            self.links.append((attrs[key], tag == "img"))


def markdown_links(text):
    """Read inline, reference-style and HTML destinations outside fenced code."""
    text = without_code(text)
    definitions = {}
    for match in re.finditer(r'^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))', text, re.M):
        definitions[match[1].casefold()] = match[2] or match[3]
    links = []
    # Backticked labels such as [`src/app.py`](...) are ordinary Markdown links.
    for match in re.finditer(r'(!?)\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"]*")?\s*\)', text):
        links.append((match[2] or match[3], bool(match[1])))
    reference_pattern = r'(!?)\[([^\]\n]+)\]\[([^\]\n]*)\]'
    for match in re.finditer(reference_pattern, text):
        label = (match[3] or match[2]).casefold()
        if label not in definitions:
            raise AssertionError(f"Undefined Markdown reference: {label}")
        links.append((definitions[label], bool(match[1])))
    shortcut_text = re.sub(reference_pattern, '', text)
    for match in re.finditer(r'(!?)\[([^\]\n]+)\](?![\[( :])', shortcut_text):
        if match[2].casefold() in definitions:
            links.append((definitions[match[2].casefold()], bool(match[1])))
    html = HTMLLinks()
    html.feed(text)
    return links + html.links


def markdown_anchors(text):
    text = without_code(text)
    html = HTMLLinks()
    html.feed(text)
    anchors = set(html.anchors)
    counts = {}
    for heading in re.findall(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
        heading = re.sub(r'<[^>]*>', '', heading).lower()
        slug = ''.join(c for c in heading if c.isalnum() or c in ' _-').replace(' ', '-')
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(slug if count == 0 else f'{slug}-{count}')
    return anchors


def local_targets(root, page):
    """Resolve all local links, including image paths and Markdown fragments."""
    root = root.resolve()
    targets = []
    for destination, image in markdown_links(page.read_text()):
        parts = urlsplit(destination)
        if parts.scheme or parts.netloc:
            continue
        resolved = (page.parent / unquote(parts.path)).resolve() if parts.path else page
        if not resolved.is_relative_to(root):
            raise AssertionError(f'{page.name}: link escapes repository: {destination}')
        if not resolved.is_file():
            raise AssertionError(f'{page.name}: missing local file: {destination}')
        if parts.fragment and resolved.suffix == '.md':
            if unquote(parts.fragment) not in markdown_anchors(resolved.read_text()):
                raise AssertionError(f'{page.name}: missing Markdown anchor: {destination}')
        targets.append((resolved, image))
    return targets


def privacy_issues(text):
    issues = []
    for candidate in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback:
            issues.append('non-loopback private IPv4')
    # Include IPv6 ULA/link-local URLs, not harmless loopback setup examples.
    for candidate in re.findall(r'https?://\[([^\]]+)\]', text):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback:
            issues.append('non-loopback private IPv6')
    patterns = (
        r'https?://[^\s/@]+:[^\s/@]+@',
        r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        r'\bgh[pousr]_[A-Za-z0-9]{20,}\b',
        r'\bgithub_pat_[A-Za-z0-9_]{20,}\b',
        r'\bhf_[A-Za-z0-9]{20,}\b',
        r'\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b',
        r'(?im)^\s*(?:export\s+)?(?:COMFY_API_KEY|API_KEY|TOKEN|PASSWORD)\s*=\s*["\']?[A-Za-z0-9_/-]{12,}',
    )
    if any(re.search(pattern, text) for pattern in patterns):
        issues.append('credential-shaped value')
    return issues


class MarkdownGuardMechanicsTests(unittest.TestCase):
    def test_nested_paths_images_references_html_and_duplicate_anchors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'image.png').write_bytes(b'fixture, not a product screenshot')
            page = root / 'docs' / 'guide.md'
            page.write_text('# A heading\n# A heading\n'
                            '[again](#a-heading-1)\n![image][shot]\n'
                            '[shot]: ../image.png\n'
                            '<a id="proof"></a><a href="#proof">Proof</a>\n'
                            '```md\n[not a link](missing.md)\n```\n')
            targets = local_targets(root, page)
            self.assertEqual(len(targets), 3)
            self.assertTrue(any(image for _, image in targets))

    def test_missing_file_anchor_escape_and_reference_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            page = root / 'guide.md'
            for broken in ('[x](absent.md)', '![x](absent.png)', '[x](#absent)',
                           '[x](../outside.md)', '[x][undefined]'):
                with self.subTest(broken=broken):
                    page.write_text('# Guide\n' + broken)
                    with self.assertRaises(AssertionError):
                        local_targets(root, page)

    def test_privacy_guard_rejects_values_but_allows_loopback(self):
        samples = (
            'http://' + '.'.join(('192', '168', '40', '12')),
            'http://' + '.'.join(('10', '20', '30', '40')),
            'http://' + '.'.join(('172', '20', '30', '40')),
            'https://[' + 'fd12::4' + ']',
            'https://user:' + 'unsafe-password' + '@example.org',
            'ghp_' + 'a' * 36,
            'API_KEY=' + 'z' * 32,
            '-----BEGIN ' + 'PRIVATE KEY-----',
        )
        for sample in samples:
            with self.subTest(kind=sample.split(':')[0][:8]):
                self.assertTrue(privacy_issues(sample))
        self.assertEqual(privacy_issues('http://127.0.0.1:8000 http://[::1]:8000'), [])


class JuryPresentationTests(unittest.TestCase):
    def read(self, name):
        path = ROOT / name
        self.assertTrue(path.is_file(), f'Missing presentation page: {name}')
        return path.read_text()

    def test_local_links_and_images_resolve_across_review_and_setup_pages(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.read(name)
                targets = local_targets(ROOT, ROOT / name)
                self.assertTrue(targets, f'{name} should link to supporting evidence')
        self.assertTrue(any(image for _, image in local_targets(ROOT, ROOT / 'README.md')),
                        'README must show a real, existing product capture')

    @unittest.skipUnless(os.environ.get('OPENGENJUTSU_JURY_REQUIRE_TRACKED') == '1',
                         'Post-staging gate; presence and tracking are separate checks')
    def test_presentation_pages_and_local_targets_are_in_git_index(self):
        paths = {ROOT / name for name in PAGES}
        for page in list(paths):
            paths.update(path for path, _ in local_targets(ROOT, page))
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT,
                                 check=True, capture_output=True).stdout.decode().split('\0')
        missing = sorted(str(path.relative_to(ROOT)) for path in paths
                         if str(path.relative_to(ROOT)) not in set(tracked))
        self.assertEqual(missing, [], f'Stage the exact reviewed files/assets first: {missing}')

    def test_above_fold_has_user_value_and_three_review_routes(self):
        intro = self.read('README.md').split('![', 1)[0]
        for destination in ('docs/jury-guide.md', '#install', '#verified-scope-and-limits'):
            self.assertIn(destination, intro)
        for idea in ('reopen', 'continue', 'character'):
            self.assertIn(idea, intro.lower())
        self.assertLess(len(intro.split()), 220, 'Keep the first screen a product invitation')

    def test_alpha_version_license_and_sdk_are_grounded_in_source(self):
        release = ast.parse((ROOT / 'src/app_release.py').read_text())
        version = next(ast.literal_eval(node.value) for node in release.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'VERSION'
                               for target in node.targets))
        for name in ('README.md', 'docs/jury-guide.md'):
            text = self.read(name)
            self.assertIn(version, text)
            self.assertIn('Apache-2.0', text)
            self.assertIn('alpha', text.lower())
        self.assertIn('Apache License', (ROOT / 'LICENSE').read_text())
        self.assertIn('from comfy_sdk import Comfy', (ROOT / 'src/comfy_transport.py').read_text())
        self.assertIn('0.5.x', self.read('README.md'))

    def test_guide_commands_match_shipped_setup_and_executor_instructions(self):
        guide = self.read('docs/jury-guide.md')
        source = self.read('README.md') + self.read('docs/executor-setup.md')
        commands = (
            'bash scripts/setup.sh --with-proxy',
            'export COMFYUI_URL=http://127.0.0.1:8188',
            'env -u PYTHONPATH .venv/bin/comfy-api-proxy run',
            '--comfyui "$COMFYUI_URL" --host 127.0.0.1 --port 8189',
            'bash scripts/run_app.sh',
            'env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine h3',
            'env -u PYTHONPATH .venv/bin/python scripts/check_dependencies.py --host http://127.0.0.1:8188 --engine ltx',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertIn(command, guide)
                self.assertIn(command, source)
        for prerequisite in ('ComfyUI', 'custom nodes', 'model weights', 'Python 3.12', 'FFmpeg', 'uv'):
            self.assertIn(prerequisite, guide)
        for boundary in ('write-only', 'Settings', 'does not install ComfyUI', 'does not submit generation'):
            self.assertIn(boundary, guide)

    def test_character_workbench_and_refinement_claims_match_current_source(self):
        character_js = (ROOT / 'src/static/character.js').read_text()
        wardrobes = re.search(r'const WARDROBES = (\[.*?\n  \]);', character_js, re.S)
        assert wardrobes is not None, 'Current wardrobe catalogue must be inspectable'
        # The literal contains strings/lists/dicts and JS trailing commas; no eval.
        self.assertEqual(sum(len(group) for group in ast.literal_eval(wardrobes[1])), 18)
        template = (ROOT / 'src/templates/character.html').read_text()
        for zone in ('recipe-panel', 'studio-stage', 'character-shelf'):
            self.assertIn(zone, template)
        face_input = re.search(r'<input[^>]+id="face-refine"[^>]*>', template)
        assert face_input is not None, 'Face-refine control must exist'
        self.assertNotRegex(face_input[0], r'\bchecked\b')
        refine = (ROOT / 'src/character_refine.py').read_text()
        self.assertRegex(refine, r'FACE_REFINE_POLICY = 2\b')
        self.assertIn('Refine only the existing face.', refine)
        self.assertIn('character_face_positive', refine)

    def test_native_capture_opt_in_and_write_only_key_match_source(self):
        h3 = (ROOT / 'src/templates/h3.html').read_text()
        capture = re.search(r'<input[^>]+id="h3-native-capture"[^>]*>', h3)
        assert capture is not None, 'Native capture control must exist'
        self.assertNotRegex(capture[0], r'\bchecked\b')
        settings = ast.parse((ROOT / 'src/compute_settings.py').read_text())
        target = next(node for node in settings.body
                      if isinstance(node, ast.ClassDef) and node.name == 'Target')
        public = next(node for node in target.body
                      if isinstance(node, ast.FunctionDef) and node.name == 'public')
        returned = next(node.value for node in public.body if isinstance(node, ast.Return))
        assert isinstance(returned, ast.Dict), 'Public Settings response must be inspectable'
        self.assertNotIn(None, returned.keys, 'Public response must not expand private dictionaries')
        keys = [ast.literal_eval(key) for key in returned.keys if key is not None]
        self.assertIn('api_key_configured', keys)
        self.assertIn('model_bindings', keys)
        self.assertNotIn('api_key', keys)

    def test_guide_separates_four_evidence_levels_and_open_acceptance(self):
        guide = self.read('docs/jury-guide.md')
        for level in ('CPU', 'Browser', 'GPU', 'Human'):
            self.assertRegex(guide, rf'\| \*\*{level}\*\* \|')
        for boundary in ('root → child → grandchild', 'Before', 'bridge', 'refine',
                         'native LTX', 'Cloud', 'upstream', 'not interchangeable',
                         'does not upload the video', 'not a complete Take backup'):
            self.assertIn(boundary, guide)
        text = self.read('README.md')
        self.assertIn('## Verified scope and limits', text)
        self.assertIn('opt-in', text)
        self.assertIn('18 wardrobe', text)

    def test_no_fake_video_marker_or_unqualified_maturity_claim(self):
        for name in ('README.md', 'docs/jury-guide.md'):
            text = self.read(name)
            with self.subTest(page=name):
                self.assertNotRegex(text, r'(?i)\b(?:TODO|COMING\s+SOON|perfect|production[ -]ready)\b')
                self.assertNotRegex(text, r'(?i)\b(?:guaranteed photorealism|five shipped styles|universally portable)\b')
                self.assertNotRegex(text, r'https?://[^\s)]*(?:VIDEO_URL|DEMO_URL|example\.com/demo)')

    def test_presentation_and_setup_have_no_private_network_or_credentials(self):
        for name in PAGES:
            with self.subTest(page=name):
                self.assertEqual(privacy_issues(self.read(name)), [])


if __name__ == '__main__':
    unittest.main()
