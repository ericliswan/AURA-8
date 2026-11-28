import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import cook  # noqa: E402
import uncook  # noqa: E402


def symbols_of(program):
    return {int(value, 0): name for name, value in
            reversed([line.split() for line in program.symbol_table().splitlines()])}


class Uncook(unittest.TestCase):
    def test_programs_round_trip_through_cook(self):
        for path in sorted((ROOT / "programs").glob("*.aura")):
            for boring in (False, True):
                with self.subTest(path.name, boring=boring):
                    program = cook.assemble(path)
                    text = uncook.listing(program.words, symbols_of(program), boring)
                    source = "".join(line + "\n" if line.endswith(":") else " " + line[10:] + "\n"
                                     for line in text.splitlines())
                    again = cook.assemble("re.aura", source=".org 0\n" + source)
                    self.assertEqual([d.format() for d in again.diagnostics if d.severity == "error"], [])
                    self.assertEqual(again.words, program.words)

    def test_fib_listing(self):
        program = cook.assemble(ROOT / "programs" / "fib.aura")
        lines = uncook.listing(program.words, symbols_of(program)).splitlines()
        self.assertEqual(lines[4:7], ["main:", "04  F800  MANIFEST R0, 0x00", "05  F901  MANIFEST R1, 0x01"])
        self.assertIn("09  9A03  FUMBLED done", lines)

    def test_missing_file(self):
        self.assertEqual(uncook.main(["/nonexistent/x.hex"]), 1)


if __name__ == "__main__":
    unittest.main()
