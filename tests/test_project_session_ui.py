import shutil
import subprocess
import unittest
from pathlib import Path

class ProjectSessionContracts(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node required')
    def test_scoped_project_session_contracts(self):
        result=subprocess.run(['node','--test','tests/project_session_contract.mjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        source=(Path(__file__).resolve().parents[1]/'src/static/app.js').read_text()
        self.assertNotRegex(source,r'function\s+history\s*\(', 'Classic studio code must not shadow the browser History API')
