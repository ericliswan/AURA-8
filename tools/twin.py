"""twin: the AURA-8 emulator and golden model (SPEC §12)."""

import argparse
import random
import signal
import sys
from collections import deque
from pathlib import Path

import isa
from isa import (ADDR_IMM, ADDR_RB, ADDR_SP, ADDR_SP1, IO_BASE, IO_REGISTERS, PC_BRANCH, PC_HOLD,
                 PC_IMM, PC_NEXT, PC_READ, PC_VECTOR, RAMEND, ROM_WORDS, SP_DEC, SP_INC,
                 VIBES_WRITABLE, WDATA_PC, WDATA_PC1)

CONTROL = isa.control_rom()
I_FLAG = 0x80
READABLE = {"VIBES", "SP", "LEDS", "BUTTONS", "HEX", "DELULU", "TCTRL", "TTOP", "TCNT", "IMASK"}
PRESCALER_BITS = (0, 3, 6, 8)
EXIT_CODES = {"halted": 0, "asleep": 0, "limit": 1, "overflow": 2}
BAD_FILE = 3

_ADDER = {
    "ADD": lambda a, b, c: (a, b, 0), "ADC": lambda a, b, c: (a, b, c),
    "SUB": lambda a, b, c: (a, b ^ 0xFF, 1), "SBC": lambda a, b, c: (a, b ^ 0xFF, c ^ 1),
    "INC": lambda a, b, c: (a, 0x00, 1), "DEC": lambda a, b, c: (a, 0xFF, 0),
    "NEG": lambda a, b, c: (0x00, a ^ 0xFF, 1),
}
_BORROWS = {"SUB", "SBC", "NEG"}
_PLAIN = {
    "AND": lambda a, b, c: a & b, "OR": lambda a, b, c: a | b, "XOR": lambda a, b, c: a ^ b,
    "PASS": lambda a, b, c: b, "COM": lambda a, b, c: a ^ 0xFF,
    "SWAP": lambda a, b, c: (a << 4 | a >> 4) & 0xFF,
    "LSR": lambda a, b, c: a >> 1, "ASR": lambda a, b, c: a >> 1 | a & 0x80,
    "ROR": lambda a, b, c: a >> 1 | c << 7,
}


def alu(op: int, a: int, b: int, vibes: int) -> tuple[int, int]:
    """Return (result, flags) where flags holds every flag the op computes, in VIBES bit positions.
    The caller masks them with isa.flag_mask(op)."""
    name = isa.ALU_OPS[op]
    carry_in, old_z = vibes & 1, vibes >> 1 & 1
    carry, overflow = carry_in, 0
    if name in _ADDER:
        x, y, cin = _ADDER[name](a, b, carry_in)
        total = x + y + cin
        result = total & 0xFF
        carry = total >> 8 ^ (name in _BORROWS)
        overflow = int(x >> 7 == y >> 7 and result >> 7 != x >> 7)
    else:
        result = _PLAIN[name](a, b, carry_in)
        if name == "COM":
            carry = 1
        elif name in ("LSR", "ASR", "ROR"):
            carry = a & 1
            overflow = result >> 7 ^ carry
    zero = int(result == 0 and (old_z or name != "SBC"))
    return result, carry | zero << 1 | (result >> 7) << 2 | overflow << 3


def read_hex(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").split("\n")
    raw = lines[0].strip() == "v2.0 raw"
    words = []
    for number, line in enumerate(lines[1:] if raw else lines, 2 if raw else 1):
        for token in line.split():
            count, _, value = token.rpartition("*") if raw else ("", "", token)
            try:
                word, repeat = int(value, 16), int(count) if count else 1
            except ValueError:
                raise ValueError(f"{path}:{number}: '{token}' isn't a hex word") from None
            if not 0 <= word <= 0xFFFF:
                raise ValueError(f"{path}:{number}: '{token}' isn't a 16-bit word")
            if repeat < 1:
                raise ValueError(f"{path}:{number}: '{token}' repeats fewer than once")
            words += [word] * repeat
    if len(words) > ROM_WORDS:
        raise ValueError(f"{path}: {len(words)} words don't fit in {ROM_WORDS}")
    return words + [0] * (ROM_WORDS - len(words))


def read_sym(path: Path) -> dict[int, str]:
    """Map addresses to labels; the first label at an address wins."""
    symbols = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        name, value = line.split()
        symbols.setdefault(int(value, 0), name)
    return symbols


def nearest_label(addr: int, symbols: dict[int, str]) -> str:
    base = max((a for a in symbols if a <= addr), default=None)
    if base is None:
        return f"0x{addr:02X}"
    return symbols[base] if base == addr else f"{symbols[base]}+{addr - base}"


class Twin:
    def __init__(self, rom: list[int], keys: dict[int, str] | None = None,
                 buttons: dict[int, int] | None = None, echo: bool = False):
        self.rom = list(rom) + [0] * (ROM_WORDS - len(rom))
        self.keys = dict(keys or {})
        self.button_script = dict(buttons or {})
        self.echo = echo
        self.regs = [0] * isa.REGISTER_COUNT
        self.ram = [0] * IO_BASE
        self.pc, self.sp, self.vibes = 0, RAMEND, 0
        self.leds = self.buttons = self.last_buttons = self.hex = 0
        self.kbd: deque[int] = deque()
        self.delulu = 0xA5
        self.tctrl = self.ttop = self.tcnt = self.prescaler = 0
        self.mrow, self.matrix = 0, [0] * 8
        self.imask = self.iflags = 0
        self.shadow = False
        self.cycle = 0
        self.tty = bytearray()
        self.chat: list[int] = []
        self.status: str | None = None
        self.min_sp = self.sp
        self.hit_brk = False
        self.dirty = False

    def iflags_value(self) -> int:
        return self.iflags | bool(self.kbd) << 2

    def peek(self, addr: int) -> int:
        if addr < IO_BASE:
            return self.ram[addr]
        name = IO_REGISTERS[addr - IO_BASE]
        if name == "KBD":
            return self.kbd[0] if self.kbd else 0
        if name == "IFLAGS":
            return self.iflags_value()
        return getattr(self, name.lower()) if name in READABLE else 0

    def _read(self, addr: int) -> int:
        if addr >= IO_BASE:
            name = IO_REGISTERS[addr - IO_BASE]
            self._kbd_read |= name == "KBD"
            self._delulu_read |= name == "DELULU"
        return self.peek(addr)

    def _write(self, addr: int, value: int) -> None:
        if addr < IO_BASE:
            self.ram[addr] = value
            return
        name = IO_REGISTERS[addr - IO_BASE]
        if name == "VIBES":
            self.vibes = value & VIBES_WRITABLE
        elif name == "SP":
            self.sp = value
        elif name == "TTY":
            self.tty.append(value)
            if self.echo:
                sys.stdout.write(chr(value))
        elif name == "CHAT":
            self.chat.append(value)
            if self.echo:
                sys.stdout.flush()
                print(f"chat: 0x{value:02X} ({value})", file=sys.stderr)
        elif name == "MDATA":
            self.matrix[self.mrow & 7] = value
            self.dirty = True
        elif name == "DELULU":
            self.delulu = value or 1
            self._delulu_written = True
        elif name == "IFLAGS":
            self._iflags_clear = value & 3
        elif name == "TCNT":
            self.tcnt = value
            self._tcnt_written = True
        elif name in ("LEDS", "HEX", "MROW", "TCTRL", "TTOP", "IMASK"):
            setattr(self, name.lower(), value)
            self.dirty |= name in ("LEDS", "HEX")

    def interrupts_possible(self) -> bool:
        return bool(self.vibes & I_FLAG and self.imask & 7)

    def step(self, trace: bool = False, symbols: dict[int, str] | None = None,
             boring: bool = False) -> str | None:
        self._kbd_read = self._delulu_read = self._delulu_written = self._tcnt_written = False
        self._iflags_clear = 0
        if self.cycle in self.keys:
            self.kbd.extend(self.keys.pop(self.cycle).encode("latin-1"))
        if self.cycle in self.button_script:
            self.buttons = self.button_script.pop(self.cycle) & 0xFF

        pending = self.iflags_value() & self.imask & 7
        take = bool(self.vibes & I_FLAG and pending and not self.shadow)
        source = (pending & -pending).bit_length() - 1 if take else None
        pc, vibes, sp = self.pc, self.vibes, self.sp
        word = isa.int_word(source + 1) if take else self.rom[pc]
        c = CONTROL[(word >> 11) << 3 | word & 7]
        a, b, imm = word >> 8 & 7, word >> 5 & 7, word & 0xFF
        ra, rb = self.regs[a], self.regs[b]
        timer = (self.prescaler, self.tctrl, self.ttop, self.tcnt)

        result, alu_flags = alu(c.alu_op, ra, imm if c.alu_b_sel else rb, vibes)
        addr = {ADDR_IMM: imm, ADDR_RB: rb, ADDR_SP: sp, ADDR_SP1: (sp + 1) & 0xFF}[c.addr_sel]
        wdata = {WDATA_PC1: (pc + 1) & 0xFF, WDATA_PC: pc}.get(c.wdata_sel, ra)
        if c.mem_we and c.addr_sel == ADDR_SP and addr >= IO_BASE:
            self.status = "overflow"
            return None
        rdata = self._read(addr) if c.mem_re else 0

        flag_mask = isa.flag_mask(c.alu_op) if c.flags_we else 0
        self.vibes = vibes & ~flag_mask | alu_flags & flag_mask
        if c.i_set:
            self.vibes |= I_FLAG
        if c.i_clr:
            self.vibes &= ~I_FLAG
        if c.reg_we:
            self.regs[a] = rdata if c.wb_sel else result
        self.sp = {SP_DEC: (sp - 1) & 0xFF, SP_INC: (sp + 1) & 0xFF}.get(c.sp_op, sp)
        branch_taken = self._condition(a, vibes)
        self.pc = {
            PC_NEXT: (pc + 1) & 0xFF, PC_IMM: imm, PC_READ: rdata, PC_HOLD: pc,
            PC_BRANCH: (pc + 1 + imm if branch_taken else pc + 1) & 0xFF,
            PC_VECTOR: imm >> 3,
        }[c.pc_sel]
        if c.mem_we:
            self._write(addr, wdata)

        self._edge(timer, source if c.int_ack else None)
        self.shadow = bool(c.shadow_set)
        self.hit_brk = bool(c.brk)
        self.min_sp = min(self.min_sp, self.sp)
        self.cycle += 1
        if c.pc_sel == PC_HOLD:
            self._check_sleep()
        if not trace:
            return None
        text = f"INT {isa.IRQ_SOURCES[source]} -> 0x{source + 1:02X}" if take else \
            isa.disassemble(word, pc, symbols, boring)
        changes = self._changes(c, a, vibes, sp, addr, wdata, branch_taken, flag_mask)
        return f"{self.cycle - 1:06d}  {pc:02X}  {word:04X}  {text:<22} {changes}".rstrip()

    @staticmethod
    def _condition(ccc: int, vibes: int) -> bool:
        z, c, n, v = vibes >> 1 & 1, vibes & 1, vibes >> 2 & 1, vibes >> 3 & 1
        return bool((z, c, n, n ^ v)[ccc >> 1] ^ ccc & 1)

    def _edge(self, timer: tuple[int, int, int, int], acked: int | None) -> None:
        prescaler, tctrl, ttop, tcnt = timer
        rising = self.buttons & ~self.last_buttons
        self.last_buttons = self.buttons
        mask = (1 << PRESCALER_BITS[tctrl >> 1 & 3]) - 1
        matched = False
        if tctrl & 1 and prescaler & mask == mask and not self._tcnt_written:
            matched = tcnt == ttop
            self.tcnt = 0 if matched else (tcnt + 1) & 0xFF
        self.prescaler = (prescaler + 1) & 0xFF
        clear = self._iflags_clear | (1 << acked if acked is not None and acked < 2 else 0)
        self.iflags = self.iflags & ~clear | matched | bool(rising) << 1
        if self._kbd_read and self.kbd:
            self.kbd.popleft()
        if self._delulu_read and not self._delulu_written:
            self.delulu = self.delulu >> 1 ^ (0xB8 if self.delulu & 1 else 0)

    def _check_sleep(self) -> None:
        if not self.interrupts_possible():
            self.status = "halted"
        elif not (self.tctrl & 1 or self.keys or self.button_script
                  or self.iflags_value() & self.imask & 7):
            self.status = "asleep"

    def _changes(self, c, a, old_vibes, old_sp, addr, wdata, branch_taken, flag_mask) -> str:
        groups = []
        if c.reg_we:
            groups.append(f"R{a}=0x{self.regs[a]:02X}")
        flags = [f"{f}={self.vibes >> isa.FLAG_BITS[f] & 1}" for f in "ZNVC"
                 if flag_mask >> isa.FLAG_BITS[f] & 1]
        if (self.vibes ^ old_vibes) & I_FLAG or c.i_set or c.i_clr:
            flags.insert(0, f"I={self.vibes >> 7}")
        if flags:
            groups.append(" ".join(flags))
        if self.sp != old_sp and not (c.mem_we and addr == isa.IO_ADDRESS["SP"]):
            groups.append(f"SP=0x{self.sp:02X}")
        if c.mem_we:
            target = IO_REGISTERS[addr - IO_BASE] if addr >= IO_BASE else f"mem[0x{addr:02X}]"
            groups.append(f"{target} <- 0x{wdata:02X}")
        if c.pc_sel == PC_BRANCH and not branch_taken:
            groups.append("not taken")
        return "  ".join(groups)

    def run(self, max_cycles: int, after_step=None) -> str:
        while self.status is None:
            if self.cycle >= max_cycles:
                self.status = "limit"
                break
            line = self.step(**(after_step.step_args if after_step else {}))
            if after_step:
                after_step(self, line)
        return self.status

    def outcome(self) -> str:
        return {
            "halted": f"touched grass after {self.cycle} cycles",
            "asleep": f"asleep forever after {self.cycle} cycles",
            "limit": f"hit the cycle limit after {self.cycle} cycles",
            "overflow": f"stack overflow at cycle {self.cycle}: a push into I/O space. You got cooked.",
        }[self.status]


def panel(tw: Twin) -> str:
    leds = "".join("●" if tw.leds >> (7 - i) & 1 else "○" for i in range(8))
    rows = ["".join("██" if row >> (7 - i) & 1 else "··" for i in range(8)) for row in tw.matrix]
    timer = f"TCTRL=0x{tw.tctrl:02X} TTOP=0x{tw.ttop:02X} TCNT=0x{tw.tcnt:02X}"
    flags = f"VIBES=0x{tw.vibes:02X} IMASK=0x{tw.imask:02X} IFLAGS=0x{tw.iflags_value():02X}"
    return "\n".join([f"cycle {tw.cycle}  LEDS {leds}  HEX {tw.hex:02X}", *rows, timer, flags])


def registers(tw: Twin) -> str:
    regs = " ".join(f"R{i}=0x{v:02X}" for i, v in enumerate(tw.regs))
    flags = "".join(f if tw.vibes >> isa.FLAG_BITS[f] & 1 else "-" for f in "IVNZC")
    return f"{regs}\nPC=0x{tw.pc:02X} SP=0x{tw.sp:02X} VIBES={flags} cycle={tw.cycle}"


def devices(tw: Twin) -> str:
    io = " ".join(f"{name}=0x{tw.peek(IO_BASE + i):02X}" for i, name in enumerate(IO_REGISTERS)
                  if name in READABLE | {"IFLAGS"})
    return f"{io}\nprescaler=0x{tw.prescaler:02X} KBD buffer={bytes(tw.kbd)!r}\n{panel(tw)}"


def stack(tw: Twin, symbols: dict[int, str]) -> str:
    lines = [f"0x{addr:02X}: 0x{tw.ram[addr]:02X}  {nearest_label(tw.ram[addr], symbols)}"
             for addr in range(tw.sp + 1, RAMEND + 1) if addr < IO_BASE]
    return "\n".join(lines) or "(empty)"


def debug(tw: Twin, max_cycles: int, symbols: dict[int, str], boring: bool) -> None:
    names = {name: addr for addr, name in symbols.items()}
    breaks: set[int] = set()
    tracing = True

    def advance(count: int | None) -> None:
        steps = 0
        while tw.status is None and (count is None or steps < count):
            if tw.cycle >= max_cycles:
                tw.status = "limit"
                break
            line = tw.step(tracing, symbols, boring)
            steps += 1
            if line:
                print(line)
            if count is None and (tw.hit_brk or tw.pc in breaks):
                break
        if tw.status:
            print(tw.outcome())

    print(registers(tw))
    while True:
        try:
            words = input("twin> ").split()
        except EOFError:
            return
        if not words:
            continue
        cmd, args = words[0], words[1:]
        try:
            if cmd == "q":
                return
            elif cmd == "s":
                advance(int(args[0], 0) if args else 1)
            elif cmd == "c":
                advance(None)
            elif cmd == "b":
                addr = names[args[0]] if args[0] in names else int(args[0], 0)
                breaks ^= {addr}
                print(f"breakpoint {'on' if addr in breaks else 'off'} at {nearest_label(addr, symbols)}")
            elif cmd == "r":
                print(registers(tw))
            elif cmd == "m":
                start, count = int(args[0], 0), int(args[1], 0) if len(args) > 1 else 16
                for row in range(start, min(start + count, 256), 16):
                    values = " ".join(f"{tw.peek(a):02X}" for a in range(row, min(row + 16, start + count, 256)))
                    print(f"0x{row:02X}: {values}")
            elif cmd == "st":
                print(stack(tw, symbols))
            elif cmd == "io":
                print(devices(tw))
            elif cmd == "t":
                tracing = not tracing
                print(f"tracing {'on' if tracing else 'off'}")
            else:
                print("commands: s [n], c, b <label|addr>, r, m <addr> [n], st, io, t, q")
        except (IndexError, ValueError, KeyError):
            print(f"can't do '{' '.join(words)}'")


def scheduled(convert):
    def parse(text: str) -> tuple[int, object]:
        cycle, sep, value = text.partition(":")
        if not sep:
            raise argparse.ArgumentTypeError(f"'{text}' should look like CYCLE:VALUE")
        try:
            return int(cycle, 0), convert(value)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e)) from None
    return parse


def key_text(text: str) -> str:
    if not text.isascii():
        raise ValueError("keys must be ASCII")
    return text


def cosmic_ray(tw: Twin, rng: random.Random) -> str:
    target, bit = rng.randrange(isa.REGISTER_COUNT + IO_BASE), rng.randrange(8)
    if target < isa.REGISTER_COUNT:
        tw.regs[target] ^= 1 << bit
        return f"cosmic ray at cycle {tw.cycle}: R{target} bit {bit}"
    addr = target - isa.REGISTER_COUNT
    tw.ram[addr] ^= 1 << bit
    return f"cosmic ray at cycle {tw.cycle}: mem[0x{addr:02X}] bit {bit}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="twin", description="Run an AURA-8 program.")
    parser.add_argument("hex", type=Path)
    parser.add_argument("--cycles", type=int, default=1_000_000)
    parser.add_argument("--key", type=scheduled(key_text), action="append", default=[], metavar="CYCLE:TEXT")
    parser.add_argument("--button", type=scheduled(lambda v: int(v, 0)), action="append", default=[],
                        metavar="CYCLE:VALUE")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--panel", action="store_true")
    parser.add_argument("--boring", action="store_true")
    parser.add_argument("--cosmic-rays", type=float, default=0.0, metavar="P")
    parser.add_argument("--seed", type=int)
    args = parser.parse_args(argv)

    try:
        rom = read_hex(args.hex)
        sym = args.hex.with_suffix(".sym")
        symbols = read_sym(sym) if sym.exists() else {}
    except (OSError, ValueError, UnicodeDecodeError) as e:
        print(f"twin: {e}", file=sys.stderr)
        return BAD_FILE

    keys: dict[int, str] = {}
    for cycle, text in args.key:
        keys[cycle] = keys.get(cycle, "") + text
    tw = Twin(rom, keys, dict(args.button), echo=True)

    if args.debug:
        debug(tw, args.cycles, symbols, args.boring)
        return EXIT_CODES.get(tw.status, 0)

    rng = random.Random(args.seed)
    clear = "\x1b[H\x1b[2J" if sys.stderr.isatty() else ""
    if args.trace:
        print("cycle   pc  word  instruction            changes")

    def after_step(machine: Twin, line: str | None) -> None:
        if line:
            print(line)
        if args.panel and machine.dirty:
            machine.dirty = False
            print(clear + panel(machine), file=sys.stderr)
        if args.cosmic_rays and rng.random() < args.cosmic_rays:
            print(cosmic_ray(machine, rng), file=sys.stderr)

    after_step.step_args = {"trace": args.trace, "symbols": symbols, "boring": args.boring}
    tw.run(args.cycles, after_step)
    sys.stdout.flush()
    if args.panel:
        print(clear + panel(tw), file=sys.stderr)
    print(tw.outcome(), file=sys.stderr)
    return EXIT_CODES[tw.status]


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
