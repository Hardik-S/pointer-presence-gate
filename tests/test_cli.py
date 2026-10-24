import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from pointer_presence_gate.cli import _present, _tokens, main


class PointerResolutionTests(unittest.TestCase):
    def test_root_empty_keys_and_rfc_escaping(self):
        value = {"": None, "a/b": {"~key": 0}, "~1": True}
        self.assertTrue(_present(value, []))
        self.assertTrue(_present(value, [""]))
        self.assertTrue(_present(value, ["a/b", "~key"]))
        self.assertEqual("/a~1b/~0key"[1:].replace("~1", "/").replace("~0", "~"), "a/b/~key")
        self.assertTrue(_present(value, ["~1"]))
        self.assertEqual(_tokens("/~01"), ["~1"])
        self.assertTrue(_present({"~1": "alias"}, _tokens("/~01")))
        self.assertTrue(_present(None, []))

    def test_null_false_zero_and_empty_values_are_present(self):
        value = {"n": None, "f": False, "z": 0, "s": "", "a": [], "o": {}}
        for key in value:
            with self.subTest(key=key):
                self.assertTrue(_present(value, [key]))

    def test_arrays_use_only_ascii_canonical_indices(self):
        values = [None]
        self.assertTrue(_present(values, ["0"]))
        for token in ("", "00", "01", "-1", "-", "١", "9" * 5000):
            with self.subTest(token=token[:20]):
                self.assertFalse(_present(values, [token]))

    def test_scalars_and_bad_array_tokens_are_unresolved(self):
        self.assertFalse(_present(None, ["x"]))
        self.assertFalse(_present({"a": []}, ["a", "-", "z"]))
        self.assertTrue(_present({"a": {"-": True}}, ["a", "-"]))


class InputAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.policy = self.root / "policy.json"
        self.rows = self.root / "rows.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def write_inputs(self, policy, rows):
        # Byte writes preserve the tested CR/LF sequence on Windows as well.
        self.policy.write_bytes(policy.encode("utf-8"))
        self.rows.write_bytes(rows.encode("utf-8"))

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(map(str, args)))
        return code, out.getvalue(), err.getvalue()

    def test_output_and_one_missing_line_per_row(self):
        self.write_inputs('{"required":["/a","/b"]}',
                          '{"id":"private-id","payload":{"a":null}}\n'
                          '{"id":"second-private-id","payload":{"a":false,"b":0}}\n')
        code, stdout, stderr = self.run_cli(self.policy, self.rows)
        self.assertEqual((code, stdout, stderr),
                         (1, '{"status":"missing_required","record_count":2,"missing_lines":[1]}\n', ""))
        self.assertNotIn("private", stdout)

    def test_empty_file_and_empty_required_list_are_valid(self):
        self.write_inputs('{"required":[]}', "")
        self.assertEqual(self.run_cli(self.policy, self.rows),
                         (0, '{"status":"valid","record_count":0,"missing_lines":[]}\n', ""))

    def test_invalid_input_is_fixed_and_silent(self):
        self.write_inputs('{"required":["#fragment"]}', '{"id":"secret","payload":{}}')
        self.assertEqual(self.run_cli(self.policy, self.rows),
                         (2, '{"status":"invalid_input"}\n', ""))
        self.assertEqual(self.run_cli("secret-policy", "secret-rows", "extra"),
                         (2, '{"status":"invalid_input"}\n', ""))
        self.assertEqual(self.run_cli("only-one"), (2, '{"status":"invalid_input"}\n', ""))

    def test_help_is_successful(self):
        code, stdout, stderr = self.run_cli("--help")
        self.assertEqual(code, 0)
        self.assertIn("usage: pointer-presence-gate", stdout)
        self.assertEqual(stderr, "")

    def test_duplicate_keys_nonfinite_and_duplicate_ids_rejected(self):
        for policy, rows in (
            ('{"required":[],"required":[]}', ''),
            ('{"required":[]}', '{"id":"x","id":"y","payload":{}}'),
            ('{"required":[]}', '{"id":"x","payload":{"n":NaN}}'),
            ('{"required":[]}', '{"id":"x","payload":{}}\n{"id":"x","payload":{}}'),
        ):
            with self.subTest(rows=rows[:20], policy=policy[:20]):
                self.write_inputs(policy, rows)
                self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_large_finite_numbers_and_exponents_are_accepted(self):
        self.write_inputs('{"required":[]}',
                          '{"id":"x","payload":{"huge":' + "9" * 5000 +
                          ',"fraction":1e9999,"tiny":-1.25E-4000}}')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 0)

    def test_policy_pointer_validation_exact_strings(self):
        for pointer in ("#", "a", "/bad~", "/bad~2", "x" * 4097):
            with self.subTest(pointer=pointer[:20]):
                self.write_inputs(json.dumps({"required": [pointer]}), "")
                self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)
        self.write_inputs('{"required":["/x","/x"]}', "")
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_unicode_normalization_is_not_applied_and_surrogates_rejected(self):
        self.write_inputs('{"required":["/é"]}', '{"id":"x","payload":{"é":1}}')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 1)
        self.write_inputs('{"required":[]}', r'{"id":"x","payload":{"x":"\ud800"}}')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_jsonl_line_endings_blank_rows_and_unicode_separators(self):
        self.write_inputs('{"required":[]}', '{"id":"a","payload":{}}\r\n{"id":"b","payload":{}}\r')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 0)
        for rows in ('\n', '{"id":"a","payload":{}}\n\n', '{"id":"a","payload":{}}\u2028'):
            with self.subTest(rows=rows):
                self.write_inputs('{"required":[]}', rows)
                self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_both_inputs_are_read_before_any_decision(self):
        self.policy.write_text('{"required":[]}', encoding="utf-8")
        self.rows.write_bytes(b"\xff")
        self.assertEqual(self.run_cli(self.policy, self.rows), (2, '{"status":"invalid_input"}\n', ""))
        self.policy.write_text('{"required":["#"]}', encoding="utf-8")
        self.rows.write_text('{"id":"x","payload":{}}', encoding="utf-8")
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_depth_127_payload_allowed_128_rejected_due_to_wrapper(self):
        payload127 = "[" * 127 + "0" + "]" * 127
        payload128 = "[" * 128 + "0" + "]" * 128
        self.write_inputs('{"required":[]}', '{"id":"x","payload":' + payload127 + '}')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 0)
        self.write_inputs('{"required":[]}', '{"id":"x","payload":' + payload128 + '}')
        self.assertEqual(self.run_cli(self.policy, self.rows)[0], 2)

    def test_exact_cli_json_is_independent_of_source_paths(self):
        self.write_inputs('{"required":[]}', '{"id":"x","payload":{}}')
        code, stdout, stderr = self.run_cli(self.policy, self.rows)
        self.assertEqual(stdout, '{"status":"valid","record_count":1,"missing_lines":[]}\n')
        self.assertEqual((code, stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
