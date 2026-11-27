"""The AURA-8 instruction set. Every other tool imports this; nothing else defines the ISA."""

from dataclasses import dataclass, fields
from typing import Callable

WORD_BITS = 16
ROM_WORDS = 256
REGISTER_COUNT = 8
RAMEND = 0xEF
IO_BASE = 0xF0

ALU_OPS = ("ADD", "ADC", "SUB", "SBC", "AND", "OR", "XOR", "PASS",
           "INC", "DEC", "COM", "NEG", "LSR", "ASR", "ROR", "SWAP")
ALU = {name: code for code, name in enumerate(ALU_OPS)}

FLAG_BITS = {"C": 0, "Z": 1, "N": 2, "V": 3, "I": 7}
VIBES_WRITABLE = 0x8F

ALU_FLAGS_WRITTEN = {
    "ADD": "ZNVC", "ADC": "ZNVC", "SUB": "ZNVC", "SBC": "ZNVC",
    "AND": "ZNV", "OR": "ZNV", "XOR": "ZNV", "PASS": "",
    "INC": "ZNV", "DEC": "ZNV", "COM": "ZNVC", "NEG": "ZNVC",
    "LSR": "ZNVC", "ASR": "ZNVC", "ROR": "ZNVC", "SWAP": "",
}


def flag_mask(alu_op: int) -> int:
    return sum(1 << FLAG_BITS[f] for f in ALU_FLAGS_WRITTEN[ALU_OPS[alu_op]])


IO_REGISTERS = ("VIBES", "SP", "LEDS", "BUTTONS", "HEX", "TTY", "KBD", "DELULU",
                "TCTRL", "TTOP", "TCNT", "MROW", "MDATA", "IMASK", "IFLAGS", "CHAT")
IO_ADDRESS = {name: IO_BASE + i for i, name in enumerate(IO_REGISTERS)}

VECTORS = {"RESET": 0, "TIMER": 1, "BUTTON": 2, "KEY": 3}
IRQ_SOURCES = ("TIMER", "BUTTON", "KEY")

PREDEFINED_SYMBOLS = {
    **IO_ADDRESS,
    "RAMEND": RAMEND,
    **{f"VEC_{name}": v for name, v in VECTORS.items()},
    **{f"IRQ_{name}": 1 << i for i, name in enumerate(IRQ_SOURCES)},
    "TIMER_DIV1": 0x01, "TIMER_DIV8": 0x03, "TIMER_DIV64": 0x05, "TIMER_DIV256": 0x07,
}

ADDR_IMM, ADDR_RB, ADDR_SP, ADDR_SP1 = range(4)
WDATA_RA, WDATA_PC1, WDATA_PC = range(3)
SP_HOLD, SP_DEC, SP_INC = range(3)
PC_NEXT, PC_IMM, PC_BRANCH, PC_READ, PC_HOLD, PC_VECTOR = range(6)


@dataclass(frozen=True)
class Control:
    """One decoder output. Field order is the control word layout, LSB first (SPEC §10.4)."""
    reg_we: int = 0
    wb_sel: int = 0
    alu_b_sel: int = 0
    alu_op: int = 0
    flags_we: int = 0
    addr_sel: int = 0
    mem_we: int = 0
    mem_re: int = 0
    wdata_sel: int = 0
    sp_op: int = 0
    pc_sel: int = 0
    i_set: int = 0
    i_clr: int = 0
    shadow_set: int = 0
    int_ack: int = 0
    brk: int = 0

    WIDTHS = {"alu_op": 4, "addr_sel": 2, "wdata_sel": 2, "sp_op": 2, "pc_sel": 3}

    @property
    def word(self) -> int:
        word, lsb = 0, 0
        for f in fields(self):
            word |= getattr(self, f.name) << lsb
            lsb += self.WIDTHS.get(f.name, 1)
        return word

    @property
    def flags(self) -> str:
        written = ALU_FLAGS_WRITTEN[ALU_OPS[self.alu_op]] if self.flags_we else ""
        return written + ("I" if self.i_set or self.i_clr else "")


CONTROL_WORD_BITS = sum(Control.WIDTHS.get(f.name, 1) for f in fields(Control))


def _alu_write(op: str, imm: int, flags: bool = True) -> Control:
    return Control(reg_we=1, alu_b_sel=imm, alu_op=ALU[op], flags_we=int(flags))


def _alu_test(op: str, imm: int) -> Control:
    return Control(alu_b_sel=imm, alu_op=ALU[op], flags_we=1)


def _load(addr_sel: int) -> Control:
    return Control(reg_we=1, wb_sel=1, addr_sel=addr_sel, mem_re=1)


def _store(addr_sel: int) -> Control:
    return Control(addr_sel=addr_sel, mem_we=1, wdata_sel=WDATA_RA)


_RETURN = dict(addr_sel=ADDR_SP1, mem_re=1, sp_op=SP_INC, pc_sel=PC_READ)


@dataclass(frozen=True)
class Form:
    """One way to write an instruction: a mnemonic plus an operand pattern.

    Operand kinds: Rd / Ra (field A), Rb / [Rb] (field B), K (constant), k (address),
    target (absolute code address), branch (code address, encoded as an offset),
    vector (INT words only), text (YAP only).
    Pseudo forms have no opcode and an `expand` that returns real (form, values) pairs.
    """
    slang: str
    boring: tuple[str, ...]
    operands: tuple[str, ...]
    description: str
    opcode: int | None = None
    a: int = 0
    sub: int = 0
    control: Control | None = None
    expand: Callable[[tuple, int], list] | None = None
    hardware_only: bool = False

    @property
    def is_pseudo(self) -> bool:
        return self.opcode is None


OP_SYS, OP_BRANCH, OP_UNARY = 0b00000, 0b10011, 0b10111

SYS = (
    ("CHILL", "NOP", "Do nothing", Control()),
    ("TOUCHGRASS", "HALT", "Stay on this instruction", Control(pc_sel=PC_HOLD)),
    ("DOOMSCROLL", "SEI", "Enable interrupts (shadow on)", Control(i_set=1, shadow_set=1)),
    ("LOCKIN", "CLI", "Disable interrupts", Control(i_clr=1)),
    ("ITSOVER", "RET", "Return from subroutine", Control(**_RETURN)),
    ("WEREBACK", "RETI", "Return from interrupt and enable interrupts",
     Control(**_RETURN, i_set=1, shadow_set=1)),
    ("BRUH", "BREAK", "Breakpoint", Control(brk=1)),
)

INT_CONTROL = Control(addr_sel=ADDR_SP, mem_we=1, wdata_sel=WDATA_PC, sp_op=SP_DEC,
                      pc_sel=PC_VECTOR, i_clr=1, int_ack=1)

UNARY = (
    ("GLOWUP", "INC", "Rd <- Rd + 1"),
    ("FELLOFF", "DEC", "Rd <- Rd - 1"),
    ("CRASHOUT", "COM", "Rd <- NOT Rd"),
    ("UNOREVERSE", "NEG", "Rd <- 0 - Rd"),
    ("LOWKEY", "LSR", "Logical shift right"),
    ("MID", "ASR", "Arithmetic shift right"),
    ("SPIN", "ROR", "Rotate right through carry"),
    ("TRADE", "SWAP", "Swap nibbles"),
)

BRANCHES = (
    ("FR", ("BREQ",), "Branch if Z = 1"),
    ("CAP", ("BRNE",), "Branch if Z = 0"),
    ("FUMBLED", ("BRLO", "BRCS"), "Branch if C = 1"),
    ("SECURED", ("BRSH", "BRCC"), "Branch if C = 0"),
    ("COOKED", ("BRMI",), "Branch if N = 1"),
    ("LETHIMCOOK", ("BRPL",), "Branch if N = 0"),
    ("MOGGED", ("BRLT",), "Branch if N XOR V = 1"),
    ("MOGGING", ("BRGE",), "Branch if N XOR V = 0"),
)

ALU_PAIRS = (
    ("AURA", "ADD", "ADDI", "+"),
    ("AURAFARM", "ADC", "ADCI", "+ C +"),
    ("TAX", "SUB", "SUBI", "-"),
    ("BACKTAX", "SBC", "SBCI", "- C -"),
    ("MUTUALS", "AND", "ANDI", "AND"),
    ("COLLAB", "OR", "ORI", "OR"),
    ("BEEF", "EOR", "EORI", "XOR"),
)


def _real_forms() -> list[Form]:
    forms = [Form(slang, (boring,), (), desc, OP_SYS, sub=sub, control=ctl)
             for sub, (slang, boring, desc, ctl) in enumerate(SYS)]
    forms.append(Form("IYKYK", ("INT",), ("vector",), "Interrupt entry (injected by hardware)",
                      OP_SYS, sub=0b111, control=INT_CONTROL, hardware_only=True))
    forms += [
        Form("STASH", ("PUSH",), ("Ra",), "M[SP] <- Ra; SP <- SP - 1", 0b00001,
             control=Control(addr_sel=ADDR_SP, mem_we=1, wdata_sel=WDATA_RA, sp_op=SP_DEC)),
        Form("VIBECHECK", ("CP",), ("Rd", "Rb"), "flags <- Rd - Rb", 0b00010,
             control=_alu_test("SUB", 0)),
        Form("DOUBLECHECK", ("CPC",), ("Rd", "Rb"), "flags <- Rd - Rb - C", 0b00011,
             control=_alu_test("SBC", 0)),
        Form("SUS", ("TST",), ("Rd", "Rb"), "flags <- Rd AND Rb", 0b00100,
             control=_alu_test("AND", 0)),
        Form("GRAB", ("POP",), ("Rd",), "SP <- SP + 1; Rd <- M[SP]", 0b00101,
             control=Control(reg_we=1, wb_sel=1, addr_sel=ADDR_SP1, mem_re=1, sp_op=SP_INC)),
        Form("LURK", ("LD",), ("Rd", "[Rb]"), "Rd <- M[Rb]", 0b00110, control=_load(ADDR_RB)),
        Form("POST", ("ST",), ("[Rb]", "Ra"), "M[Rb] <- Ra", 0b00111, control=_store(ADDR_RB)),
    ]
    for col, (slang, reg_name, imm_name, op) in enumerate(ALU_PAIRS):
        alu_op = ALU_OPS[col]
        forms.append(Form(slang, (reg_name,), ("Rd", "Rb"), f"Rd <- Rd {op} Rb", 0b01000 | col,
                          control=_alu_write(alu_op, 0)))
        forms.append(Form(slang, (imm_name,), ("Rd", "K"), f"Rd <- Rd {op} K", 0b11000 | col,
                          control=_alu_write(alu_op, 1)))
    forms += [
        Form("LARP", ("MOV",), ("Rd", "Rb"), "Rd <- Rb", 0b01111,
             control=_alu_write("PASS", 0, flags=False)),
        Form("MANIFEST", ("LDI",), ("Rd", "K"), "Rd <- K", 0b11111,
             control=_alu_write("PASS", 1, flags=False)),
        Form("BET", ("JMP",), ("target",), "PC <- k", 0b10000, control=Control(pc_sel=PC_IMM)),
        Form("HITUP", ("CALL",), ("target",), "M[SP] <- PC + 1; SP <- SP - 1; PC <- k", 0b10001,
             control=Control(addr_sel=ADDR_SP, mem_we=1, wdata_sel=WDATA_PC1, sp_op=SP_DEC,
                             pc_sel=PC_IMM)),
        Form("VIBECHECK", ("CPI",), ("Rd", "K"), "flags <- Rd - K", 0b10010,
             control=_alu_test("SUB", 1)),
        Form("SUS", ("TSTI",), ("Rd", "K"), "flags <- Rd AND K", 0b10100,
             control=_alu_test("AND", 1)),
        Form("LURK", ("LDS",), ("Rd", "k"), "Rd <- M[k]", 0b10101, control=_load(ADDR_IMM)),
        Form("POST", ("STS",), ("k", "Ra"), "M[k] <- Ra", 0b10110, control=_store(ADDR_IMM)),
    ]
    forms += [Form(slang, boring, ("branch",), desc, OP_BRANCH, a=ccc,
                   control=Control(pc_sel=PC_BRANCH))
              for ccc, (slang, boring, desc) in enumerate(BRANCHES)]
    forms += [Form(slang, (boring,), ("Rd",), desc, OP_UNARY, sub=sub,
                   control=Control(reg_we=1, alu_op=0b1000 | sub, flags_we=1))
              for sub, (slang, boring, desc) in enumerate(UNARY)]
    return forms


REAL_FORMS = _real_forms()


def form(slang: str, *operands: str) -> Form:
    match = next((f for f in REAL_FORMS if f.slang == slang and f.operands == operands), None)
    if match is None:
        raise KeyError(f"no real form {slang} {operands}")
    return match


def _yap(values: tuple, _addr: int) -> list:
    (text,) = values
    if any(ord(ch) > 0xFF for ch in text):
        raise ValueError("YAP characters must fit in 8 bits")
    manifest, post, tty = form("MANIFEST", "Rd", "K"), form("POST", "k", "Ra"), IO_ADDRESS["TTY"]
    chars = [step for ch in text for step in ((manifest, (7, ord(ch))), (post, (tty, 7)))]
    return [(form("STASH", "Ra"), (7,)), *chars, (form("GRAB", "Rd"), (7,))]


def _same_register(slang: str) -> Callable:
    return lambda values, _addr: [(form(slang, "Rd", "Rb"), (values[0], values[0]))]


def _load_constant(k: int) -> Callable:
    return lambda values, _addr: [(form("MANIFEST", "Rd", "K"), (values[0], k))]


PSEUDO_FORMS = [
    Form("HIGHKEY", ("LSL",), ("Rd",), "Shift left: AURA Rd, Rd", expand=_same_register("AURA")),
    Form("NIPS", ("ROL",), ("Rd",), "Rotate left through carry: AURAFARM Rd, Rd",
         expand=_same_register("AURAFARM")),
    Form("GHOST", ("CLR",), ("Rd",), "Clear: BEEF Rd, Rd", expand=_same_register("BEEF")),
    Form("SUS", ("TST",), ("Rd",), "Test for zero or negative: SUS Rd, Rd",
         expand=_same_register("SUS")),
    Form("MAXX", ("SER",), ("Rd",), "Set all bits: MANIFEST Rd, 0xFF", expand=_load_constant(0xFF)),
    Form("SIXSEVEN", (), ("Rd",), "MANIFEST Rd, 67", expand=_load_constant(67)),
    Form("BRAINROT", (), (), "Infinite loop: BET .",
         expand=lambda _values, addr: [(form("BET", "target"), (addr,))]),
    Form("YAP", (), ("text",), "Print a string, preserving every register and flag", expand=_yap),
]


def _index_mnemonics() -> dict[str, list[Form]]:
    index: dict[str, list[Form]] = {}
    for f in REAL_FORMS + PSEUDO_FORMS:
        if f.hardware_only:
            continue
        for name in {f.slang, *f.boring}:
            index.setdefault(name, []).append(f)
    return index


MNEMONICS = _index_mnemonics()


def word_count(f: Form, values: tuple) -> int:
    return 2 * len(values[0]) + 2 if "text" in f.operands else 1


OPERAND_FIELDS = {  # kind -> (shift, mask) within the 16-bit word
    "Rd": (8, 7), "Ra": (8, 7), "Rb": (5, 7), "[Rb]": (5, 7), "vector": (3, 0x1F),
    "K": (0, 0xFF), "k": (0, 0xFF), "target": (0, 0xFF), "branch": (0, 0xFF),
}


def encode(f: Form, values: tuple, addr: int) -> list[int]:
    """Encode one statement. Values are already range-checked; constants may be negative."""
    if f.is_pseudo:
        return [w for real, vals in f.expand(values, addr) for w in encode(real, vals, addr)]
    word = f.opcode << 11 | f.a << 8 | f.sub
    for kind, value in zip(f.operands, values):
        if kind == "branch":
            value -= addr + 1
        shift, mask = OPERAND_FIELDS[kind]
        word |= (value & mask) << shift
    return [word]


def _decode_table() -> dict[tuple[int, int, int], Form]:
    table = {}
    for f in REAL_FORMS:
        a = f.a if f.opcode == OP_BRANCH else 0
        subs = [f.sub] if f.opcode in (OP_SYS, OP_UNARY) else range(8)
        for sub in subs:
            table[f.opcode, a, sub] = f
    return table


_DECODE = _decode_table()


def decode_form(opcode: int, a: int, sub: int) -> Form:
    return _DECODE[opcode, a if opcode == OP_BRANCH else 0, sub]


def decode(word: int, addr: int = 0) -> tuple[Form, tuple, bool]:
    """Return (form, operand values, nonstandard). Branch operands decode to absolute targets."""
    f = decode_form(word >> 11, (word >> 8) & 7, word & 7)
    values = []
    for kind in f.operands:
        shift, mask = OPERAND_FIELDS[kind]
        value = (word >> shift) & mask
        values.append((addr + 1 + value) & 0xFF if kind == "branch" else value)
    values = tuple(values)
    return f, values, encode(f, values, addr) != [word]


def control_rom() -> list[Control]:
    """Decoder ROM contents, addressed by {opcode, instr[2:0]} (SPEC §10.6)."""
    return [decode_form(addr >> 3, 0, addr & 7).control for addr in range(256)]


def int_word(vector: int) -> int:
    return encode(form("IYKYK", "vector"), (vector,), 0)[0]


def _hex8(value: int) -> str:
    return f"0x{value:02X}"


def format_operand(kind: str, value, symbols: dict[int, str]) -> str:
    if kind in ("Rd", "Ra", "Rb"):
        return f"R{value}"
    if kind == "[Rb]":
        return f"[R{value}]"
    if kind in ("target", "branch"):
        return symbols.get(value, _hex8(value))
    if kind == "k":
        return IO_REGISTERS[value - IO_BASE] if value >= IO_BASE else _hex8(value)
    return _hex8(value)


def disassemble(word: int, addr: int = 0, symbols: dict[int, str] | None = None,
                boring: bool = False) -> str:
    f, values, nonstandard = decode(word, addr)
    name = f.boring[0] if boring else f.slang
    ops = ", ".join(format_operand(k, v, symbols or {}) for k, v in zip(f.operands, values))
    text = f"{name} {ops}".rstrip()
    notes = ["INT (hardware only)"] * f.hardware_only + ["nonstandard"] * nonstandard
    return f"{text}  ; {', '.join(notes)}" if notes else text
