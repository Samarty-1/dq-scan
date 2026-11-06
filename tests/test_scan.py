import pathlib
import subprocess
import sys
import unittest


class LegacyScanTests(unittest.TestCase):
    def test_basic_scan(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'dq_scan.py'),
                                 str(root / 'examples/sample.csv')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('nulls=1', result.stdout)
        self.assertIn('currency', result.stdout)


if __name__ == '__main__':
    unittest.main()
