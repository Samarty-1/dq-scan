import json
import pathlib
import subprocess
import sys
import unittest


class CommandOptionsTests(unittest.TestCase):
    def run_command(self, *args):
        root = pathlib.Path(__file__).resolve().parents[1]
        return subprocess.run([sys.executable, str(root / 'dq_scan.py'), *args],
                              cwd=root, capture_output=True, text=True)

    def test_documented_table_alias(self):
        result = self.run_command('--table', 'examples/sample.csv', '--format', 'json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['row_count'], 5)

    def test_documented_rules_example(self):
        result = self.run_command('examples/sample.csv', '--config', 'examples/rules.json',
                                  '--format', 'json', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual([f['code'] for f in report['findings']],
                         ['null_threshold', 'out_of_range'])

    def test_invalid_arguments(self):
        for args in [[], ['absent.csv'], ['examples/sample.csv', '--null-threshold', '2'],
                     ['examples/sample.csv', '--table', 'examples/sample.csv'],
                     ['examples/sample.csv', '--delimiter', '"']]:
            with self.subTest(args=args):
                result = self.run_command(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
