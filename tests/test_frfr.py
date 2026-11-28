import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import frfr  # noqa: E402


def run(source):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.aura"
        path.write_text(source)
        out = io.StringIO()
        with redirect_stdout(out):
            code = frfr.main([d])
        return code, out.getvalue()


class Frfr(unittest.TestCase):
    def test_parse(self):
        spec = frfr.parse('; frfr: cycles 50\n; frfr: key 3 "a\\n"\n; frfr: key 3 "b"\n'
                          '; frfr: button 9 0x01\n; frfr: expect chat == [1, 0x02]\n'
                          '; frfr: expect R3 == 0b11\n; frfr: expect mem[16] == 7\n')
        self.assertEqual((spec.cycles, spec.keys, spec.buttons), (50, {3: "a\nb"}, {9: 1}))
        self.assertEqual(spec.expects, [("chat", [1, 2]), ("R3", 3), ("mem[0x10]", 7)])
        self.assertIsNone(frfr.parse("CHILL\n"))

    def test_bad_directive(self):
        for text in ("expect R9 == 1", "expect mem[0x100] == 0", 'key 0 "\\xE9"', 'key 0 "\u20ac"'):
            with self.subTest(text), self.assertRaises(ValueError):
                frfr.parse(f"; frfr: {text}\n")

    def test_pass_and_fail(self):
        self.assertEqual(run("; frfr: expect R0 == 5\n; frfr: expect halted\nMANIFEST R0, 5\nTOUCHGRASS\n")[0], 0)
        code, out = run("; frfr: expect R0 == 6\nMANIFEST R0, 5\nTOUCHGRASS\n")
        self.assertEqual(code, 1)
        self.assertIn("FAIL (cap detected)", out)
        self.assertIn("R0: expected 0x06 (6), got 0x05 (5)", out)

    def test_overflow_exit(self):
        source = "; frfr: expect exit == 2\nMANIFEST R0, 0xF0\nPOST SP, R0\nSTASH R0\nTOUCHGRASS\n"
        self.assertEqual(run(source)[0], 0)


if __name__ == "__main__":
    unittest.main()
