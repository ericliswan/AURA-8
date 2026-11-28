import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import gen_alu_vectors as gen  # noqa: E402
import isa  # noqa: E402


def row(op, a, b, cin=0, zin=0):
    return gen.vector(isa.ALU[op], a, b, cin, zin).split()[5:]


class GenAluVectors(unittest.TestCase):
    def test_coverage(self):
        lines = gen.vectors().splitlines()
        self.assertEqual(lines[1], gen.HEADER)
        self.assertEqual(len(lines) - 2, 8 * 256 * 2 + 8 * 25 * 4 + 5000)
        self.assertEqual(gen.vectors(10, seed=3), gen.vectors(10, seed=3))

    def test_spec_flag_rules(self):
        self.assertEqual(row("ADD", 0x7F, 0x01), ["0x80", "0", "1", "1", "0"])
        self.assertEqual(row("SUB", 0x00, 0x01), ["0xFF", "0", "1", "0", "1"])
        self.assertEqual(row("SBC", 0x01, 0x01, zin=0), ["0x00", "0", "0", "0", "0"])
        self.assertEqual(row("SBC", 0x01, 0x01, zin=1), ["0x00", "1", "0", "0", "0"])
        self.assertEqual(row("AND", 0x80, 0xFF, cin=1), ["0x80", "0", "1", "0", "x"])
        self.assertEqual(row("PASS", 0x00, 0x00), ["0x00", "x", "x", "x", "x"])
        self.assertEqual(row("NEG", 0x80, 0x00), ["0x80", "0", "1", "1", "1"])
        self.assertEqual(row("ROR", 0x01, 0x00, cin=1), ["0x80", "0", "1", "0", "1"])

    def test_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hw" / "v.txt"
            self.assertEqual(gen.main(["-o", str(out), "--random", "0"]), 0)
            self.assertEqual(len(out.read_text().splitlines()), 2 + 8 * 256 * 2 + 8 * 25 * 4)


if __name__ == "__main__":
    unittest.main()
