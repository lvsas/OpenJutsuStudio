"""Offline distribution guard for the unmodified Apache License 2.0 text."""

import hashlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
# SHA-256 of https://www.apache.org/licenses/LICENSE-2.0.txt (official text).
APACHE_2_0_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"


class LicenseDistributionTest(unittest.TestCase):
    def test_root_license_is_complete_official_apache_2_0(self):
        actual = hashlib.sha256((ROOT / "LICENSE").read_bytes()).hexdigest()
        self.assertEqual(actual, APACHE_2_0_SHA256, "root LICENSE differs from the official Apache-2.0 text")


if __name__ == "__main__":
    unittest.main()
