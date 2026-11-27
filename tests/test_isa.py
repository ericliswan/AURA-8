import unittest

import isa


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

    def test_mnemonic_counts(self):
        slang = {f.slang for f in isa.REAL_FORMS if not f.hardware_only}
        pseudo = {f.slang for f in isa.PSEUDO_FORMS if f.slang not in slang}
        self.assertEqual(len(slang), 41)
        self.assertEqual(len(pseudo), 7)


class Decoding(unittest.TestCase):
    FIB = [0x8004, 0x0005, 0x0005, 0x0005, 0xF800, 0xF901, 0xB0FF, 0x7A00,
           0x4220, 0x9A03, 0x7820, 0x7940, 0x8006, 0xB1FF, 0x0001]

    def test_every_word_round_trips(self):
        for word in range(1 << 16):
            f, values, nonstandard = isa.decode(word, 0x40)
            reencoded = isa.encode(f, values, 0x40)[0]
            self.assertEqual(reencoded == word, not nonstandard, hex(word))

    def test_fib_listing(self):
        text = [isa.disassemble(w, addr) for addr, w in enumerate(self.FIB)]
        self.assertEqual(text[6], "POST CHAT, R0")
        self.assertEqual(text[9], "FUMBLED 0x0D")
        self.assertEqual(text[14], "TOUCHGRASS")

    def test_nonstandard_and_int(self):
        self.assertEqual(isa.disassemble(0x0020), "CHILL  ; nonstandard")
        self.assertEqual(isa.disassemble(0x0017), "IYKYK 0x02  ; INT (hardware only)")
        self.assertEqual(isa.disassemble(0x0001, boring=True), "HALT")


if __name__ == "__main__":
    unittest.main()
