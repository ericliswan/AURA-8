import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import cook  # noqa: E402

PROGRAMS = ROOT / "programs"


def cook_source(source, path="t.aura", werror=False):
    return cook.assemble(path, source=source, werror=werror)


def messages(program, severity="error"):
    return [d.error.message for d in program.diagnostics if d.severity == severity]


class SpecProgramTests(unittest.TestCase):
    def test_all_programs_cook_cleanly(self):
        for path in sorted(PROGRAMS.glob("*.aura")):
            with self.subTest(path.name):
                self.assertEqual(cook.assemble(path).diagnostics, [])

    def test_hello_hex_prefix(self):
        hexfile = cook.format_hex(cook.assemble(PROGRAMS / "hello.aura").words)
        self.assertTrue(hexfile.startswith(
            "v2.0 raw\n"
            "8004 0005 0005 0005 0f00 ff61 b7f5 ff75\n"
            "b7f5 ff72 b7f5 ff61 b7f5 ff20 b7f5 ff2b\n"))
        self.assertEqual(len(hexfile.splitlines()), 33)

    def test_fib_words_and_symbols(self):
        program = cook.assemble(PROGRAMS / "fib.aura")
        self.assertEqual(program.words[:15], [
            0x8004, 0x0005, 0x0005, 0x0005, 0xF800, 0xF901, 0xB0FF, 0x7A00,
            0x4220, 0x9A03, 0x7820, 0x7940, 0x8006, 0xB1FF, 0x0001])
        self.assertEqual(program.words[15:], [0] * 241)
        self.assertEqual(program.symbol_table(), "main 0x04\nloop 0x06\ndone 0x0D\n")

    def test_listing_shows_every_word(self):
        listing = cook.assemble(PROGRAMS / "hello.aura").listing().splitlines()
        self.assertEqual(listing[0], "addr word   source")
        self.assertTrue(any(line.startswith("05   FF61") for line in listing))


class ExpressionTests(unittest.TestCase):
    def value(self, expr):
        program = cook_source(f".org 0\n.word {expr}\n")
        self.assertEqual(program.diagnostics, [], expr)
        return program.words[0]

    def test_precedence_and_truncating_division(self):
        self.assertEqual(self.value("(1 << 4) | 3 + -7 / 2"), 0x10)
        self.assertEqual(self.value("-7 % 2 & 0xFFFF"), 0xFFFF)
        self.assertEqual(self.value("2 + 3 * 4"), 14)

    def test_lo_hi_char_and_dot(self):
        self.assertEqual(self.value("hi(0x1234)"), 0x12)
        self.assertEqual(self.value("lo(0x1234)"), 0x34)
        self.assertEqual(self.value("'A'"), 0x41)
        self.assertEqual(cook_source(".org 0x10\n.word .\n").words[0x10], 0x10)

    def test_bad_expressions(self):
        for expr, error in [("1 / 0", "division by zero"), ("1 << 64", "shift by 64 is out of range")]:
            with self.subTest(expr):
                self.assertIn(error, messages(cook_source(f".word {expr}\n")))


class DirectiveTests(unittest.TestCase):
    def test_equ_and_def(self):
        program = cook_source(".equ N = 5\n.def acc = R3\n.org 0\n MANIFEST acc, N + 1\n TOUCHGRASS\n")
        self.assertEqual(program.diagnostics, [])
        self.assertEqual(program.words[0], 0xFB06)

    def test_include_resolves_relative_and_detects_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "consts.inc").write_text(".equ SEVEN = 7\n")
            (tmp / "loop.inc").write_text('.include "loop.inc"\n')
            main = tmp / "main.aura"
            ok = cook.assemble(main, source='.include "consts.inc"\n.org 0\n MANIFEST R0, SEVEN\n TOUCHGRASS\n')
            self.assertEqual(ok.diagnostics, [])
            self.assertEqual(ok.words[0], 0xF807)
            looped = cook.assemble(main, source='.include "loop.inc"\n')
            self.assertTrue(any("include" in m for m in messages(looped)), messages(looped))

    def test_overlap(self):
        program = cook_source(".org 0\n CHILL\n CHILL\n.org 1\n CHILL\n")
        self.assertIn("two things at 0x01 (lines 3 and 5)", messages(program))


class DiagnosticTests(unittest.TestCase):
    def first(self, source, **kw):
        return cook_source(source, **kw).diagnostics[0]

    def test_format_with_caret_and_roast(self):
        diag = self.first(".org 0\nmain:   STAHS R0\n")
        self.assertEqual(diag.format(), "\n".join([
            "t.aura:2:9: error: unknown mnemonic 'STAHS'",
            "    2 | main:   STAHS R0",
            "      |         ^^^^^",
            "      = did you mean STASH? typing is hard, chief"]))
        self.assertTrue(diag.format(boring=True).endswith("= did you mean STASH?"))

    def test_operand_errors(self):
        cases = [
            (" AURA 5, R1\n", "AURA takes (reg, reg) or (reg, K); got (K, reg)"),
            (" MANIFEST R9, 1\n", "there is no R9"),
            (" MANIFEST R0, 300\n", "300 doesn't fit in 8 bits (-128..255)"),
            (" LURK R1, 0x1A0\n", "address 0x1A0 is outside 0x00..0xFF"),
            (" FUMBLED nope\n", "undefined symbol 'nope'"),
            ('a: CHILL\na: CHILL\n', "'a' already defined on line 2"),
            (' YAP "a\\q"\n', "unknown escape '\\q'"),
            (" .frob 3\n", "unknown directive '.frob'"),
            (' YAP "\u0100"\n', "'\u0100' doesn't fit in 8 bits"),
            ("INT: CHILL\n", None),
        ]
        for source, error in cases:
            with self.subTest(source):
                errors = messages(cook_source(".org 0\n" + source))
                self.assertIn(error, errors) if error else self.assertTrue(errors)

    def test_rom_overflow(self):
        for source in (" CHILL\n" * 257, ".org 0xFF\n CHILL\n BRAINROT\n"):
            with self.subTest(source[:12]):
                program = cook_source(".org 0\n" + source)
                self.assertIn("needs 257 words; ROM holds 256", messages(program))

    def test_warnings_and_werror(self):
        source = ".org 0\n BET main\nmain: TOUCHGRASS\nspare: CHILL\n"
        self.assertEqual(messages(cook_source(source), "warning"), ["label 'spare' is never used"])
        self.assertTrue(cook_source(source, werror=True).failed)


if __name__ == "__main__":
    unittest.main()
