import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import cook  # noqa: E402
import isa  # noqa: E402
import twin  # noqa: E402

PROGRAMS = ROOT / "programs"


def machine(name=None, source=None, **kwargs):
    program = cook.assemble(PROGRAMS / name) if name else cook.assemble("t.aura", source=source)
    return twin.Twin(program.words, **kwargs)


def alu(name, a, b=0, vibes=0):
    op = isa.ALU_OPS.index(name)
    result, flags = twin.alu(op, a, b, vibes)
    return result, flags & isa.flag_mask(op)


class Alu(unittest.TestCase):
    C, Z, N, V = 1, 2, 4, 8

    def test_adder(self):
        self.assertEqual(alu("ADD", 0x7F, 0x01), (0x80, self.N | self.V))
        self.assertEqual(alu("ADD", 0xFF, 0x01), (0x00, self.Z | self.C))
        self.assertEqual(alu("SUB", 0x00, 0x01), (0xFF, self.N | self.C))
        self.assertEqual(alu("SUB", 0x80, 0x01), (0x7F, self.V))
        self.assertEqual(alu("NEG", 0x80), (0x80, self.N | self.V | self.C))

    def test_sbc_borrows_and_keeps_zero_across_bytes(self):
        self.assertEqual(alu("SBC", 0x00, 0x00, vibes=self.C), (0xFF, self.N | self.C))
        self.assertEqual(alu("SBC", 0x05, 0x04, vibes=self.Z | self.C), (0x00, self.Z))
        self.assertEqual(alu("SBC", 0x05, 0x05, vibes=0), (0x00, 0))

    def test_shifts(self):
        self.assertEqual(alu("ROR", 0x01, vibes=self.C), (0x80, self.N | self.C))
        self.assertEqual(alu("ASR", 0x81)[0], 0xC0)
        self.assertEqual(alu("SWAP", 0x12)[0], 0x21)


class Programs(unittest.TestCase):
    def test_hello(self):
        tw = machine("hello.aura")
        self.assertEqual(tw.run(1000), "halted")
        self.assertEqual((bytes(tw.tty), tw.cycle), (b"aura +1\n", 20))

    def test_fib(self):
        tw = machine("fib.aura")
        tw.run(10_000)
        self.assertEqual(tw.chat, [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233])

    def test_math(self):
        tw = machine("math.aura")
        self.assertEqual(tw.run(10_000), "halted")
        self.assertEqual((tw.chat, tw.cycle, tw.min_sp), ([0x60, 0x18, 120], 350, 0xE6))

    def test_tick(self):
        tw = machine("tick.aura", keys={1000: "hi"})
        ints = []

        def watch(machine, line):
            if line and " INT " in line:
                ints.append(int(line[:6]))
        watch.step_args = {"trace": True}
        self.assertEqual(tw.run(4000, watch), "limit")
        self.assertEqual((bytes(tw.tty), tw.hex, tw.ram[0]), (b"hi", 4, 4))
        self.assertEqual(ints, [800, 1600, 2400, 3200])


class Machine(unittest.TestCase):
    def test_push_into_io_space_overflows(self):
        tw = machine(source="MANIFEST R0, 0xF0\nPOST SP, R0\nSTASH R0\nTOUCHGRASS\n")
        self.assertEqual(tw.run(100), "overflow")

    def test_sleep_with_nothing_to_wake_it(self):
        tw = machine(source="MANIFEST R0, 1\nPOST IMASK, R0\nDOOMSCROLL\nTOUCHGRASS\n")
        self.assertEqual(tw.run(100), "asleep")

    def test_delulu_steps_after_read(self):
        tw = machine(source="LURK R0, DELULU\nLURK R1, DELULU\nTOUCHGRASS\n")
        tw.run(100)
        self.assertEqual(tw.regs[:2], [0xA5, 0xA5 >> 1 ^ 0xB8])

    def test_io_reads(self):
        tw = machine(source="LURK R0, SP\nLURK R1, TTY\nLURK R2, KBD\nLURK R3, KBD\nTOUCHGRASS\n",
                     keys={0: "ab"})
        tw.run(100)
        self.assertEqual(tw.regs[:4], [0xEF, 0, ord("a"), ord("b")])


class Files(unittest.TestCase):
    def test_read_hex_run_length_and_padding(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.hex"
            path.write_text("v2.0 raw\n3*1 abcd\n")
            self.assertEqual(twin.read_hex(path)[:5], [1, 1, 1, 0xABCD, 0])
            for bad in ("257*0", "0*1", "-1*0", "-1", "10000"):
                path.write_text(f"v2.0 raw\n{bad}\n")
                with self.subTest(bad), self.assertRaises(ValueError):
                    twin.read_hex(path)

    def test_cli_exit_codes_and_trace(self):
        with tempfile.TemporaryDirectory() as d:
            program = cook.assemble(PROGRAMS / "fib.aura")
            hexfile = Path(d) / "fib.hex"
            hexfile.write_text(cook.format_hex(program.words))
            (Path(d) / "fib.sym").write_text(program.symbol_table())
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(twin.main([str(hexfile), "--trace"]), 0)
                self.assertEqual(twin.main([str(hexfile), "--cycles", "5"]), 1)
                self.assertEqual(twin.main([str(Path(d) / "missing.hex")]), 3)
                with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
                    twin.main([str(hexfile), "--key", "0:\u20ac"])
            lines = out.getvalue().splitlines()
            self.assertIn("000006  09  9A03  FUMBLED done           not taken", lines)
            self.assertIn("chat: 0x0D (13)", err.getvalue())


if __name__ == "__main__":
    unittest.main()
