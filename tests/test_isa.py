import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import isa  # noqa: E402


def encode_one(slang, operands, values, addr=0):
    return isa.encode(isa.form(slang, *operands), values, addr)


class ControlWord(unittest.TestCase):
    def test_spec_examples(self):
        self.assertEqual(isa.form("AURA", "Rd", "Rb").control.word, 0x000081)
        self.assertEqual(isa.form("MANIFEST", "Rd", "K").control.word, 0x00003D)
        self.assertEqual(isa.form("HITUP", "target").control.word, 0x015600)

    def test_rom_covers_every_address(self):
        rom = isa.control_rom()
        self.assertEqual(len(rom), 256)
        self.assertEqual(rom[0b00000_111], isa.INT_CONTROL)
        self.assertTrue(all(c.word < 1 << isa.CONTROL_WORD_BITS for c in rom))


class Encoding(unittest.TestCase):
    def test_drills(self):
        self.assertEqual(encode_one("TAX", ("Rd", "K"), (3, 7)), [0xD307])
        self.assertEqual(encode_one("MANIFEST", ("Rd", "K"), (0, -5)), [0xF8FB])
        self.assertEqual(encode_one("FR", ("branch",), (0x0A,), 0x10), [0x98F9])

    def test_int_words(self):
        self.assertEqual([isa.int_word(v) for v in (1, 2, 3)], [0x000F, 0x0017, 0x001F])

    def test_yap_expansion(self):
        words = isa.encode(isa.MNEMONICS["YAP"][0], ("hi",), 0)
        self.assertEqual(words, [0x0F00, 0xFF68, 0xB7F5, 0xFF69, 0xB7F5, 0x2F00])

    def test_yap_rejects_wide_characters(self):
        with self.assertRaises(ValueError):
            isa.encode(isa.MNEMONICS["YAP"][0], ("\u2192",), 0)

    def test_mnemonic_counts(self):
        slang = {f.slang for f in isa.REAL_FORMS if not f.hardware_only}
        pseudo = {f.slang for f in isa.PSEUDO_FORMS if f.slang not in slang}
        self.assertEqual(len(slang), 41)
        self.assertEqual(len(pseudo), 7)

    def test_pseudo_expansion_encodes_each_word_at_its_own_address(self):
        skip_twice = isa.Form("SKIP2", (), (), "test-only", expand=lambda _v, addr: [
            (isa.form("FR", "branch"), (addr + 2,)), (isa.form("FR", "branch"), (addr + 2,))])
        self.assertEqual(isa.encode(skip_twice, (), 0x10), [0x9801, 0x9800])

    def test_word_count_matches_expansion(self):
        for f in isa.PSEUDO_FORMS:
            values = ("hi",) if "text" in f.operands else (1,) * len(f.operands)
            with self.subTest(f.slang):
                self.assertEqual(isa.word_count(f, values), len(isa.encode(f, values, 0)))

    def test_reserved_names(self):
        self.assertEqual(isa.RESERVED_NAMES, {"IYKYK", "INT"})


class Decoding(unittest.TestCase):
    def test_rejects_words_wider_than_16_bits(self):
        for word in (-1, 0x10000):
            with self.assertRaises(ValueError):
                isa.decode(word)

    FIB = [0x8004, 0x0005, 0x0005, 0x0005, 0xF800, 0xF901, 0xB0FF, 0x7A00,
           0x4220, 0x9A03, 0x7820, 0x7940, 0x8006, 0xB1FF, 0x0001]

    @staticmethod
    def must_be_zero(word):
        opcode = word >> 11
        if opcode == isa.OP_SYS:
            return 0x0700 if word & 7 == 7 else 0x07F8
        if opcode in (0b00001, 0b00101):
            return 0x00FF
        if opcode in (0b10000, 0b10001):
            return 0x0700
        if opcode == isa.OP_UNARY:
            return 0x00F8
        return 0x001F if opcode >> 3 == 0b01 or opcode in (0b00010, 0b00011, 0b00100, 0b00110, 0b00111) else 0

    def test_nonstandard_means_must_be_zero_bits_set(self):
        for word in range(1 << 16):
            f, values, nonstandard = isa.decode(word, 0x40)
            self.assertEqual(nonstandard, bool(word & self.must_be_zero(word)), hex(word))
            standard = word & ~self.must_be_zero(word)
            self.assertEqual(isa.encode(f, values, 0x40), [standard], hex(word))

    def test_fib_listing(self):
        text = [isa.disassemble(w, addr) for addr, w in enumerate(self.FIB)]
        self.assertEqual(text[6], "POST CHAT, R0")
        self.assertEqual(text[9], "FUMBLED 0x0D")
        self.assertEqual(text[14], "TOUCHGRASS")

    def test_nonstandard_and_int(self):
        self.assertEqual(isa.disassemble(0x0020), "CHILL  ; nonstandard")
        self.assertEqual(isa.disassemble(0x0017), "IYKYK 0x02  ; INT (hardware only)")
        self.assertEqual(isa.disassemble(0x0117), "IYKYK 0x02  ; INT (hardware only), nonstandard")
        self.assertEqual(isa.disassemble(0x0001, boring=True), "HALT")

    def test_operand_fields(self):
        self.assertEqual(isa.disassemble(0x3260), "LURK R2, [R3]")
        self.assertEqual(isa.disassemble(0x3B40), "POST [R2], R3")
        self.assertEqual(isa.disassemble(0x0B00), "STASH R3")
        self.assertEqual(isa.disassemble(0xBC00), "GLOWUP R4")
        self.assertEqual(isa.disassemble(0x98FF, 0x10), "FR 0x10")


if __name__ == "__main__":
    unittest.main()
