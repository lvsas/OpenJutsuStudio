"""Branding contracts: real template sources, canonical SVG and isolated HTTP.

The HTTP fixture serves files only; it never imports the app, opens live data or
runs client scripts. Browser layout/journey acceptance remains a separate check.
"""
import functools
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "src/static/brand"
CANONICAL_PATH = "M21 7H7v18h18V14H15v5h5"
PAGES = {
    "index": ("/", "favicon-ltx.svg", "#22d3ee"),
    "character": ("/characters", "favicon.svg", "#d8ff3e"),
    "h3": ("/h3", "favicon-h3.svg", "#ff4f2e"),
    "timeline": ("/timeline", "favicon-timeline.svg", "#bc5cff"),
    "settings": ("/settings", "favicon.svg", "#d8ff3e"),
}


class Links(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.in_head = False
        self.icons = []
        self.styles = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "head":
            self.in_head = True
        if self.in_head and tag == "link":
            if attrs.get("rel") == "icon":
                self.icons.append(attrs)
            if attrs.get("rel") == "stylesheet":
                self.styles.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "head":
            self.in_head = False


def template(name):
    return (ROOT / f"src/templates/{name}.html").read_text()


def assert_g(case, svg, stroke):
    case.assertEqual(svg.attrib["viewBox"], "0 0 32 32")
    children = list(svg)
    case.assertEqual([node.tag.split("}")[-1] for node in children], ["rect", "path"])
    case.assertEqual(children[0].attrib, {"width": "32", "height": "32", "rx": "8", "fill": "#101014"})
    case.assertEqual(children[1].attrib, {
        "d": CANONICAL_PATH, "stroke": stroke, "stroke-width": "3", "fill": "none",
    })


class BrandingContract(unittest.TestCase):
    def test_five_heads_reference_existing_accented_favicons(self):
        for name, (_, asset, accent) in PAGES.items():
            with self.subTest(page=name):
                links = Links(template(name))
                self.assertEqual(links.icons, [{"rel": "icon", "type": "image/svg+xml", "href": f"/static/brand/{asset}"}])
                path = BRAND / asset
                self.assertTrue(path.is_file(), f"Missing favicon: {path}")
                assert_g(self, ET.fromstring(path.read_bytes()), accent)

    def test_inline_wordmarks_share_canonical_geometry_and_studio_color(self):
        for name in PAGES:
            with self.subTest(page=name):
                source = template(name)
                wordmark = re.search(r'<a class="wordmark"[^>]*>(.*?)</a>', source, re.S).group(1)
                self.assertNotIn("✦", wordmark)
                match = re.search(r"<svg\b.*?</svg>", wordmark, re.S)
                self.assertIsNotNone(match, "Wordmark needs the canonical inline G")
                svg = ET.fromstring(match.group(0))
                assert_g(self, svg, "currentColor")
                self.assertEqual(svg.attrib["aria-hidden"], "true")
                self.assertEqual(svg.attrib["focusable"], "false")
                self.assertEqual(svg.attrib["width"], "24")
                self.assertEqual(svg.attrib["height"], "24")
                self.assertEqual(svg.attrib["class"], "brand-mark")
                self.assertNotIn("style", svg.attrib)
                self.assertIn(".wordmark .brand-mark { color: var(--accent)",
                              (ROOT / "src/static/app.css").read_text())
                self.assertEqual(re.sub(r"<[^>]+>", "", wordmark), "OPENGENJUTSU")

    def test_favicon_accents_match_linked_studio_styles(self):
        for name, (_, _, expected) in PAGES.items():
            with self.subTest(page=name):
                accents = []
                for href in Links(template(name)).styles:
                    css = (ROOT / "src" / href.lstrip("/")).read_text()
                    accents.extend(re.findall(r"--accent\s*:\s*(#[0-9a-fA-F]{6})\s*;", css))
                self.assertTrue(accents, "No studio accent loaded")
                self.assertEqual(accents[-1].lower(), expected)

    def test_static_variants_regenerate_identically(self):
        builder = ROOT / "tools/build_brand_assets.py"
        self.assertTrue(builder.is_file(), "Missing single-master brand builder")
        with tempfile.TemporaryDirectory(prefix="brand-contract-") as directory:
            subprocess.run([sys.executable, str(builder), "--output-dir", directory], check=True, capture_output=True, text=True)
            generated = {path.name: path.read_bytes() for path in Path(directory).glob("*.svg")}
            committed = {path.name: path.read_bytes() for path in BRAND.glob("*.svg")}
            self.assertEqual(len(generated), 4)
            self.assertEqual(generated, committed)

    def test_isolated_read_only_http_serves_five_pages_and_four_svg_assets(self):
        routes = {route: f"/templates/{name}.html" for name, (route, _, _) in PAGES.items()}

        class ReadOnlyFiles(SimpleHTTPRequestHandler):
            def do_GET(self):
                self.path = routes.get(self.path, self.path)
                super().do_GET()

            def do_HEAD(self):
                self.path = routes.get(self.path, self.path)
                super().do_HEAD()

            def log_message(self, *_):
                pass

        handler = functools.partial(ReadOnlyFiles, directory=str(ROOT / "src"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            self.assertNotEqual(port, 8000)
            base = f"http://{host}:{port}"
            served_assets = set()
            for name, (route, asset, accent) in PAGES.items():
                with self.subTest(page=name):
                    with urlopen(base + route, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers.get_content_type(), "text/html")
                        source = response.read().decode()
                    self.assertEqual(source, template(name))
                    self.assertEqual(len(Links(source).icons), 1)
                    href = Links(source).icons[0]["href"]
                    self.assertEqual(href, f"/static/brand/{asset}")
                    with urlopen(base + href, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers.get_content_type(), "image/svg+xml")
                        content = response.read()
                    self.assertEqual(content, (BRAND / asset).read_bytes())
                    assert_g(self, ET.fromstring(content), accent)
                    with urlopen(Request(base + href, method="HEAD"), timeout=5) as response:
                        self.assertEqual(response.status, 200)
                    served_assets.add(href)
            self.assertEqual(len(served_assets), 4)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/", method="POST", data=b""), timeout=5)
            self.assertEqual(error.exception.code, 501)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
