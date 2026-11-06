import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

import dq_scan


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)

    def source(self, text):
        path = self.root / 'data.csv'
        path.write_text(text, encoding='utf-8', newline='')
        return path

    def cli(self, path, *args):
        return subprocess.run([sys.executable, str(pathlib.Path(dq_scan.__file__)),
                               str(path), *args], capture_output=True, text=True)

    def test_report_metrics_and_duplicate_records(self):
        path = self.source('id,amount,label\n1,10,A\n2,,B\n1,10,A\n')
        report = dq_scan.audit_csv(path)
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(report['row_count'], 3)
        self.assertEqual(report['duplicate_rows'], 1)
        amount = report['columns'][1]
        self.assertEqual(amount['null_count'], 1)
        self.assertEqual(amount['distinct_count'], 1)
        self.assertEqual(amount['duplicate_values'], 1)
        self.assertEqual(amount['numeric'], {'count': 2, 'min': 10.0, 'max': 10.0, 'mean': 10.0})

    def test_composite_key_nulls_and_duplicates(self):
        report = dq_scan.audit_csv(self.source('id,site\n1,A\n1,B\n1,A\n,B\n'),
                                   key_columns=['id', 'site'])
        self.assertEqual(report['key']['duplicate_count'], 1)
        self.assertEqual(report['key']['null_count'], 1)
        self.assertEqual({f['code'] for f in report['findings']} &
                         {'duplicate_key', 'null_key'}, {'duplicate_key', 'null_key'})

    def test_range_and_invalid_numbers(self):
        report = dq_scan.audit_csv(self.source('amount\n-1\n0\n10\n11\nword\n'),
                                   ranges={'amount': {'min': 0, 'max': 10}})
        col = report['columns'][0]
        self.assertEqual(col['out_of_range_count'], 2)
        self.assertEqual(col['invalid_numeric_count'], 1)
        self.assertEqual(col['type'], 'mixed')

    def test_header_only_is_valid(self):
        report = dq_scan.audit_csv(self.source('id,amount\n'))
        self.assertEqual(report['row_count'], 0)
        self.assertEqual(report['columns'][0]['null_fraction'], 0)
        self.assertEqual(report['findings'], [])

    def test_empty_file_is_rejected(self):
        with self.assertRaises(ValueError):
            dq_scan.audit_csv(self.source(''))

    def test_malformed_input_is_rejected(self):
        for text in ['a,a\n1,2\n', 'a,\n1,2\n', 'a,b\n1\n',
                     'a,b\n1,2,3\n', 'a\n"unterminated\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                dq_scan.audit_csv(self.source(text))

    def test_bom_delimiter_and_quoted_newline(self):
        report = dq_scan.audit_csv(self.source('\ufeffid;note\r\n1;"a\r\nb"\r\n'), delimiter=';')
        self.assertEqual(report['row_count'], 1)
        self.assertEqual(report['columns'][0]['name'], 'id')

    def test_whitespace_is_null_but_na_is_text(self):
        report = dq_scan.audit_csv(self.source('a,b\n ,NA\n1,NULL\n'))
        self.assertEqual(report['columns'][0]['null_count'], 1)
        self.assertEqual(report['columns'][1]['null_count'], 0)

    def test_nonfinite_values_never_leak_into_json(self):
        report = dq_scan.audit_csv(self.source('x\nNaN\nInfinity\n1e309\n1\n'))
        self.assertEqual(report['columns'][0]['nonfinite_count'], 3)
        json.dumps(report, allow_nan=False)
        self.assertIn('nonfinite_number', {f['code'] for f in report['findings']})

    def test_extreme_finite_mean(self):
        report = dq_scan.audit_csv(self.source('x\n1e308\n-1e308\n'))
        self.assertEqual(report['columns'][0]['numeric']['mean'], 0.0)
        json.dumps(report, allow_nan=False)

    def test_unknown_columns_and_bad_options(self):
        path = self.source('id\n1\n')
        for kwargs in [{'key_columns': ['missing']}, {'key_columns': ['id', 'id']},
                       {'null_threshold': -1}, {'null_threshold': float('nan')},
                       {'ranges': {'missing': {'min': 0}}},
                       {'ranges': {'id': {'min': 10, 'max': 0}}},
                       {'ranges': {'id': {'min': float('inf')}}}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                dq_scan.audit_csv(path, **kwargs)

    def test_threshold_boundary(self):
        path = self.source('a,b\n,1\n2,3\n')
        self.assertNotIn('null_threshold', {f['code'] for f in dq_scan.audit_csv(path, null_threshold=.5)['findings']})
        self.assertIn('null_threshold', {f['code'] for f in dq_scan.audit_csv(path, null_threshold=.49)['findings']})

    def test_cli_json_and_failure_policy(self):
        path = self.source('id,value\n1,\n1,3\n')
        result = self.cli(path, '--format', 'json', '--key', 'id', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)['key']['duplicate_count'], 1)
        self.assertEqual(self.cli(path, '--fail-on', 'error').returncode, 0)
        self.assertEqual(self.cli(path, '--fail-on', 'warning').returncode, 1)
        self.assertEqual(self.cli(path).returncode, 0)

    def test_cli_config_and_override(self):
        path = self.source('a,b\n,1\n2,3\n')
        config = self.root / 'rules.json'
        config.write_text(json.dumps({'null_threshold': 0}), encoding='utf8')
        result = self.cli(path, '--config', str(config), '--null-threshold', '1', '--format', 'json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['findings'], [])

    def test_bad_config_and_data_exit_two_without_partial_report(self):
        path = self.source('a,a\n1,2\n')
        result = self.cli(path, '--format', 'json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        config = self.root / 'rules.json'
        config.write_text('{"typo": 1}', encoding='utf8')
        self.assertEqual(self.cli(self.source('a\n1\n'), '--config', str(config)).returncode, 2)

    def test_invalid_utf8_is_not_silently_replaced(self):
        path = self.root / 'bad.csv'
        path.write_bytes(b'name\n\xff\n')
        self.assertEqual(self.cli(path).returncode, 2)

    def test_source_is_not_modified(self):
        path = self.source('id\n1\n1\n')
        before = path.read_bytes()
        dq_scan.audit_csv(path)
        self.assertEqual(path.read_bytes(), before)

    def test_mean_preserves_subnormal_and_cancellation(self):
        for values, expected in [('5e-324\n5e-324\n', 5e-324),
                                 ('1e308\n1\n-1e308\n', 1 / 3)]:
            with self.subTest(values=values):
                report = dq_scan.audit_csv(self.source('x\n' + values))
                self.assertEqual(report['columns'][0]['numeric']['mean'], expected)

    def test_exact_large_integer_range_boundary(self):
        report = dq_scan.audit_csv(self.source('x\n9007199254740993\n'),
                                   ranges={'x': {'min': 9007199254740993,
                                                 'max': 9007199254740993}})
        self.assertEqual(report['columns'][0]['out_of_range_count'], 0)

    def test_bare_quotes_rejected_and_escaped_quotes_accepted(self):
        with self.assertRaises(ValueError):
            dq_scan.audit_csv(self.source('a\nx"y\n'))
        report = dq_scan.audit_csv(self.source('a,b\n"x""y",z\n'))
        self.assertEqual(report['row_count'], 1)

    def test_unsupported_decimal_exponent_is_an_input_error(self):
        path = self.source('x\n1e-9999999999999999999\n')
        with self.assertRaises(ValueError):
            dq_scan.audit_csv(path, ranges={'x': {'min': 0}})
        config = self.root / 'rules.json'
        config.write_text('{"ranges": {"x": {"min": 0}}}', encoding='utf8')
        result = self.cli(path, '--config', str(config), '--format', 'json')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
