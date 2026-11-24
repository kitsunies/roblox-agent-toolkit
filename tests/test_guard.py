"""The optional PreToolUse guard's own self-check."""
from pathlib import Path
import subprocess
import sys
import unittest

HOOK = Path(__file__).resolve().parents[1] / "hooks/studio-mcp-guard.py"


class GuardTests(unittest.TestCase):
    def test_self_check(self):
        result = subprocess.run([sys.executable, str(HOOK), "--self-check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
