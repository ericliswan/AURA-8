#!/usr/bin/env python3
"""cook: the AURA-8 assembler (SPEC §11). Let him cook."""

import argparse
import difflib
import operator
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import isa

ROASTS = {
    "mnemonic": "typing is hard, chief",
    "operands": "be so fr",
    "immediate": "that's too much aura for one byte",
    "address": "that address is delulu",
    "symbol": "it's giving typo.",
    "duplicate": "no clones",
    "overlap": "this spot is taken",
    "size": "you're cooked (hint: YAP costs 2 words per character)",
    "register": "there are 8 registers. count them.",
    "syntax": "the parser said ratio",
    "name": "that name is taken, bestie",
    "include": "new file who dis",
    "word": "that's too much aura for one word",
    "vector": "an interrupt there slides into the next vector",
    "unused": "left on read",
    "int_word": "cursed",
    "yap": "it works, but why",
}

K_RANGE = (-128, 255)
ADDRESS_RANGE = (0, 0xFF)
WORD_RANGE = (-0x8000, 0xFFFF)
MAX_SHIFT = 64
MAX_NUMBER_DIGITS = 66
WEREBACK_WORD = isa.encode(isa.form("WEREBACK"), (), 0)[0]
REGISTER = re.compile(r"[Rr](\d+)")
NAME = re.compile(r"[A-Za-z_]\w*")
LABEL = re.compile(r"\s*([A-Za-z_]\w*)\s*:")
DIRECTIVES = (".org", ".equ", ".def", ".word", ".include")
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", "'": "'", '"': '"'}
TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<number>0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+)
  | (?P<char>'(?:\\x[0-9A-Fa-f]{2}|\\.|[^\\'])')
  | (?P<name>[A-Za-z_]\w*)
  | (?P<op><<|>>|[-~*/%+&^|(),.])
""", re.VERBOSE)
BINARY_LEVELS = (("|",), ("^",), ("&",), ("<<", ">>"), ("+", "-"), ("*", "/", "%"))
SYNTAX = {"Rd": "reg", "Ra": "reg", "Rb": "reg", "[Rb]": "ptr", "K": "expr", "k": "expr",
          "target": "expr", "branch": "expr", "text": "text"}
SHOWN_FORM = {"Rd": "reg", "Ra": "reg", "Rb": "reg", "[Rb]": "[reg]", "K": "K", "k": "k",
              "target": "label", "branch": "label", "text": "string"}
SHOWN_KIND = {"reg": "reg", "ptr": "[reg]", "expr": "K", "text": "string"}


class AsmError(Exception):
    def __init__(self, kind: str, message: str, col: int | None = None, width: int = 1,
                 hint: str | None = None):
        super().__init__(message)
        self.kind, self.message, self.col, self.width, self.hint = kind, message, col, width, hint


@dataclass(frozen=True)
class Line:
    file: str
    number: int
    text: str


@dataclass(frozen=True)
class Operand:
    text: str
    col: int


@dataclass
class Diagnostic:
    severity: str
    line: Line
    error: AsmError

    def format(self, boring: bool = False) -> str:
        err, text = self.error, self.line.text
        col, width = err.col, err.width
        if col is None:
            col = len(text) - len(text.lstrip()) + 1
            width = max(1, len(text.strip()))
        indent = "".join(c if c == "\t" else " " for c in text[:col - 1])
        out = [f"{self.line.file}:{self.line.number}:{col}: {self.severity}: {err.message}",
               f"{self.line.number:5} | {text}",
               f"      | {indent}{'^' * width}"]
        note = " ".join(filter(None, (err.hint, None if boring else ROASTS.get(err.kind))))
        if note:
            out.append(f"      = {note}")
        return "\n".join(out)


@dataclass
class Statement:
    line: Line
    addr: int
    form: isa.Form | None = None
    operands: list = field(default_factory=list)
    size: int = 0
    is_word: bool = False
    words: list[int] = field(default_factory=list)
    constants_known: int = 0


@dataclass
class Program:
    words: list[int]
    statements: list[Statement]
    labels: dict[str, int]
    diagnostics: list[Diagnostic]

    @property
    def failed(self) -> bool:
        return any(d.severity == "error" for d in self.diagnostics)

    def listing(self) -> str:
        out = ["addr word   source"]
        for stmt in self.statements:
            text = stmt.line.text.rstrip()
            if not stmt.words:
                out.append(f"{stmt.addr:02X}          {text}")
            for i, word in enumerate(stmt.words):
                out.append(f"{stmt.addr + i:02X}   {word:04X}   {text}".rstrip() if i == 0
                           else f"{stmt.addr + i:02X}   {word:04X}")
        return "\n".join(out) + "\n"

    def symbol_table(self) -> str:
        return "".join(f"{name} 0x{value:02X}\n"
                       for name, value in sorted(self.labels.items(), key=lambda kv: (kv[1], kv[0])))


def format_hex(words: list[int], fmt: str = "raw") -> str:
    if fmt == "plain":
        return "".join(f"{w:04x}\n" for w in words)
    rows = (" ".join(f"{w:04x}" for w in words[i:i + 8]) for i in range(0, len(words), 8))
    return "v2.0 raw\n" + "\n".join(rows) + "\n"


def suggest(word: str, candidates) -> str | None:
    matches = difflib.get_close_matches(word, list(candidates), n=1, cutoff=0.6)
    return matches[0] if matches else None


def unescape(body: str, col: int) -> str:
    out, i = [], 0
    while i < len(body):
        if body[i] != "\\":
            out.append(body[i])
            i += 1
            continue
        code = body[i + 1:i + 2]
        hex_digits = body[i + 2:i + 4]
        if code == "x" and re.fullmatch(r"[0-9A-Fa-f]{2}", hex_digits):
            out.append(chr(int(hex_digits, 16)))
            i += 4
        elif code and code in ESCAPES:
            out.append(ESCAPES[code])
            i += 2
        else:
            raise AsmError("syntax", f"unknown escape '\\{code}'", col + i, 2)
    return "".join(out)


def strip_comment(text: str) -> str:
    quote, escaped = None, False
    for i, c in enumerate(text):
        if escaped:
            escaped = False
        elif quote and c == "\\":
            escaped = True
        elif quote:
            quote = None if c == quote else quote
        elif c in "\"'":
            quote = c
        elif c == ";":
            return text[:i]
    return text


def split_operands(text: str, col: int) -> list[Operand]:
    if not text.strip():
        return []
    pieces, start, depth, quote, escaped = [], 0, 0, None, False
    for i, c in enumerate(text + ","):
        if escaped:
            escaped = False
        elif quote:
            escaped = c == "\\"
            quote = None if c == quote else quote
        elif c in "\"'":
            quote = c
        elif c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "," and depth == 0:
            piece = text[start:i]
            stripped = piece.strip()
            lead = len(piece) - len(piece.lstrip())
            if not stripped:
                raise AsmError("syntax", "missing operand", col + start, 1)
            pieces.append(Operand(stripped, col + start + lead))
            start = i + 1
    return pieces


class Expression:
    """Recursive-descent evaluator with C precedence; integers are unbounded until range-checked."""

    def __init__(self, text: str, col: int, lookup):
        self.lookup, self.tokens, self.pos = lookup, [], 0
        offset = 0
        while offset < len(text):
            match = TOKEN.match(text, offset)
            if not match:
                raise AsmError("syntax", f"unexpected '{text[offset]}'", col + offset)
            if match.lastgroup != "space":
                self.tokens.append((match.lastgroup, match.group(), col + offset))
            offset = match.end()
        self.end_col = col + len(text)

    def evaluate(self) -> int:
        value = self.binary(0)
        if self.pos < len(self.tokens):
            _, text, col = self.tokens[self.pos]
            raise AsmError("syntax", f"unexpected '{text}'", col, len(text))
        return value

    def peek(self) -> tuple[str, str, int]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ("end", "", self.end_col)

    def take(self) -> tuple[str, str, int]:
        token = self.peek()
        self.pos += 1
        return token

    def expect(self, text: str) -> None:
        kind, found, col = self.take()
        if found != text:
            raise AsmError("syntax", f"expected '{text}'", col, max(1, len(found)))

    def binary(self, level: int) -> int:
        if level == len(BINARY_LEVELS):
            return self.unary()
        left = self.binary(level + 1)
        while self.peek()[0] == "op" and self.peek()[1] in BINARY_LEVELS[level]:
            _, op, col = self.take()
            left = apply_binary(op, left, self.binary(level + 1), col)
        return left

    def unary(self) -> int:
        kind, text, col = self.take()
        if kind == "op" and text == "-":
            return -self.unary()
        if kind == "op" and text == "~":
            return ~self.unary()
        if kind == "op" and text == "(":
            value = self.binary(0)
            self.expect(")")
            return value
        if kind == "op" and text == ".":
            return self.lookup(".", col, 1)
        if kind == "number":
            base = {"0x": 16, "0b": 2}.get(text[:2].lower(), 10)
            if len(text) > MAX_NUMBER_DIGITS:
                raise AsmError("syntax", "number is too long", col, len(text))
            return int(text[2:] if base != 10 else text, base)
        if kind == "char":
            return ord(unescape(text[1:-1], col + 1))
        if kind == "name" and text.lower() in ("lo", "hi") and self.peek()[1] == "(":
            self.take()
            value = self.binary(0)
            self.expect(")")
            return value & 0xFF if text.lower() == "lo" else (value >> 8) & 0xFF
        if kind == "name":
            return self.lookup(text, col, len(text))
        raise AsmError("syntax", "expected a value" if kind == "end" else f"unexpected '{text}'",
                       col, max(1, len(text)))


BINARY_OPS = {"|": operator.or_, "^": operator.xor, "&": operator.and_, "<<": operator.lshift,
              ">>": operator.rshift, "+": operator.add, "-": operator.sub, "*": operator.mul}


def apply_binary(op: str, a: int, b: int, col: int) -> int:
    if op in "/%" and b == 0:
        raise AsmError("syntax", "division by zero", col)
    if op in ("<<", ">>") and not 0 <= b < MAX_SHIFT:
        raise AsmError("syntax", f"shift by {b} is out of range", col, 2)
    if op == "/":
        quotient = abs(a) // abs(b)
        return quotient if (a < 0) == (b < 0) else -quotient
    if op == "%":
        return a - b * apply_binary("/", a, b, col)
    result = BINARY_OPS[op](a, b)
    if result.bit_length() > MAX_SHIFT:
        raise AsmError("syntax", "value is too large", col)
    return result


def check_text(text: str, op: Operand) -> None:
    wide = next((ch for ch in text if ord(ch) > 0xFF), None)
    if wide:
        raise AsmError("immediate", f"'{wide}' doesn't fit in 8 bits", op.col, len(op.text))


def check_range(value: int, bounds: tuple[int, int], op: Operand) -> int:
    low, high = bounds
    if low <= value <= high:
        return value
    if bounds == K_RANGE:
        raise AsmError("immediate", f"{value} doesn't fit in 8 bits (-128..255)", op.col, len(op.text))
    if bounds == WORD_RANGE:
        raise AsmError("word", f"{value} doesn't fit in 16 bits", op.col, len(op.text))
    raise AsmError("address", f"address {value:#X} is outside 0x00..0xFF".replace("0X", "0x"),
                   op.col, len(op.text))


class Assembler:
    def __init__(self, werror: bool = False):
        self.werror = werror
        self.diagnostics: list[Diagnostic] = []
        self.statements: list[Statement] = []
        self.labels: dict[str, tuple[int, Line, int]] = {}
        self.constants: dict[str, int] = {}
        self.constant_order: dict[str, int] = {}
        self.visible_constants: int | None = None
        self.aliases: dict[str, int] = {}
        self.defined_on: dict[str, Line] = {}
        self.used: set[str] = set()
        self.addr = 0
        self.words = [0] * isa.ROM_WORDS
        self.owner: dict[int, Line] = {}

    def report(self, line: Line, err: AsmError, severity: str = "error") -> None:
        if severity == "warning" and self.werror:
            severity = "error"
        self.diagnostics.append(Diagnostic(severity, line, err))

    def warn(self, line: Line, err: AsmError) -> None:
        self.report(line, err, "warning")

    # Pass 1: lines, directives, label addresses.

    def read_file(self, path: Path, display: str, text: str, including: tuple[Path, ...]) -> None:
        for number, raw in enumerate(text.splitlines(), 1):
            line = Line(display, number, raw)
            try:
                self.first_pass(line, path, including)
            except AsmError as err:
                self.report(line, err)

    def first_pass(self, line: Line, path: Path, including: tuple[Path, ...]) -> None:
        text = strip_comment(line.text)
        rest_col = 0
        label = LABEL.match(text)
        if label:
            rest_col = label.end()
            try:
                self.define_label(label.group(1), label.start(1) + 1, line)
            except AsmError as err:
                self.report(line, err)
        head = re.compile(r"\s*(\.?\w+)").match(text, rest_col)
        if not head:
            if text[rest_col:].strip():
                raise AsmError("syntax", "expected a mnemonic or directive", rest_col + 1)
            if label:
                self.statements.append(Statement(line, self.addr, constants_known=len(self.constants)))
            return
        name, col = head.group(1), head.start(1) + 1
        rest, rest_col = text[head.end():], head.end() + 1
        if name.startswith("."):
            self.directive(name, col, rest, rest_col, line, path, including)
        else:
            self.instruction(name, col, rest, rest_col, line)

    def check_name(self, name: str, col: int) -> None:
        if name in self.defined_on:
            raise AsmError("duplicate", f"'{name}' already defined on line {self.defined_on[name].number}",
                           col, len(name))
        upper = name.upper()
        reason = ("a mnemonic" if upper in isa.MNEMONICS or upper in isa.RESERVED_NAMES
                  else "a register" if REGISTER.fullmatch(name)
                  else "a predefined symbol" if name in isa.PREDEFINED_SYMBOLS
                  else None)
        if reason:
            raise AsmError("name", f"'{name}' is {reason}", col, len(name))

    def define_label(self, name: str, col: int, line: Line) -> None:
        self.check_name(name, col)
        self.labels[name] = (self.addr, line, col)
        self.defined_on[name] = line

    def directive(self, name: str, col: int, rest: str, rest_col: int, line: Line,
                  path: Path, including: tuple[Path, ...]) -> None:
        directive = name.lower()
        if directive in (".equ", ".def"):
            match = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*=\s*(.*?)\s*", rest)
            if not match or not match.group(2):
                raise AsmError("syntax", f"expected '{directive} NAME = value'", col, len(name))
            target, target_col = match.group(1), rest_col + match.start(1)
            value = Operand(match.group(2), rest_col + match.start(2))
            self.check_name(target, target_col)
            if directive == ".equ":
                self.constants[target] = self.evaluate(value, self.addr)
                self.constant_order[target] = len(self.constant_order)
            else:
                register = self.register(value)
                if register is None:
                    raise AsmError("syntax", f"'{value.text}' isn't a register", value.col, len(value.text))
                self.aliases[target] = register
            self.defined_on[target] = line
            return
        operands = split_operands(rest, rest_col)
        if directive == ".org":
            if len(operands) != 1:
                raise AsmError("syntax", ".org takes one address", col, len(name))
            self.addr = check_range(self.evaluate(operands[0], self.addr), ADDRESS_RANGE, operands[0])
        elif directive == ".word":
            if not operands:
                raise AsmError("syntax", ".word needs at least one value", col, len(name))
            self.statements.append(Statement(line, self.addr, operands=operands, size=len(operands),
                                             is_word=True, constants_known=len(self.constants)))
            self.addr += len(operands)
        elif directive == ".include":
            self.include(operands, col, name, line, path, including)
        else:
            hint = suggest(directive, DIRECTIVES)
            raise AsmError("syntax", f"unknown directive '{name}'", col, len(name),
                           f"did you mean {hint}?" if hint else None)

    def include(self, operands: list[Operand], col: int, name: str, line: Line,
                path: Path, including: tuple[Path, ...]) -> None:
        if len(operands) != 1 or not operands[0].text.startswith('"'):
            raise AsmError("syntax", '.include takes one "file"', col, len(name))
        op = operands[0]
        relative = unescape(op.text[1:-1], op.col + 1)
        target = path.parent / relative
        if target.resolve() in including:
            raise AsmError("include", f"'{relative}' includes itself", op.col, len(op.text))
        try:
            text = target.read_text()
        except OSError as err:
            raise AsmError("include", f"can't read '{relative}': {err.strerror}", op.col, len(op.text))
        display = str(Path(line.file).parent / relative)
        self.read_file(target, display, text, including + (target.resolve(),))

    def instruction(self, name: str, col: int, rest: str, rest_col: int, line: Line) -> None:
        forms = isa.MNEMONICS.get(name.upper())
        stmt = Statement(line, self.addr, size=1, constants_known=len(self.constants))
        self.statements.append(stmt)
        self.addr += 1
        if not forms:
            hint = suggest(name.upper(), isa.MNEMONICS)
            raise AsmError("mnemonic", f"unknown mnemonic '{name}'", col, len(name),
                           f"did you mean {hint}?" if hint else None)
        operands = [self.classify(op) for op in split_operands(rest, rest_col)]
        for kind, payload, op in operands:
            if kind == "text":
                check_text(payload, op)
        kinds = tuple(kind for kind, _, _ in operands)
        stmt.form = next((f for f in forms if tuple(SYNTAX[o] for o in f.operands) == kinds), None)
        if stmt.form is None:
            raise self.operand_mismatch(name, forms, kinds, col)
        stmt.operands = operands
        stmt.size = isa.word_count(stmt.form, tuple(payload for _, payload, _ in operands))
        self.addr += stmt.size - 1

    @staticmethod
    def operand_mismatch(name: str, forms: list[isa.Form], kinds: tuple, col: int) -> AsmError:
        wanted = " or ".join(f"({', '.join(SHOWN_FORM[o] for o in f.operands)})" for f in forms)
        got = f"({', '.join(SHOWN_KIND[k] for k in kinds)})"
        return AsmError("operands", f"{name.upper()} takes {wanted}; got {got}", col, len(name))

    def register(self, op: Operand) -> int | None:
        match = REGISTER.fullmatch(op.text)
        if match:
            number = int(match.group(1))
            if number >= isa.REGISTER_COUNT:
                raise AsmError("register", f"there is no R{number}", op.col, len(op.text))
            return number
        return self.aliases.get(op.text)

    def classify(self, op: Operand) -> tuple[str, object, Operand]:
        text = op.text
        if text.startswith('"'):
            if len(text) < 2 or not text.endswith('"'):
                raise AsmError("syntax", "unterminated string", op.col, len(text))
            return "text", unescape(text[1:-1], op.col + 1), op
        if text.startswith("["):
            if not text.endswith("]"):
                raise AsmError("syntax", "missing ']'", op.col, len(text))
            inner = text[1:-1].strip()
            register = self.register(Operand(inner, op.col + text.index(inner)))
            if register is None:
                raise AsmError("syntax", f"[{inner}] needs a register inside", op.col, len(text))
            return "ptr", register, op
        register = self.register(op)
        if register is not None:
            return "reg", register, op
        return "expr", text, op

    def evaluate(self, op: Operand, addr: int) -> int:
        return Expression(op.text, op.col, lambda name, col, width: self.lookup(name, col, width, addr)
                          ).evaluate()

    def lookup(self, name: str, col: int, width: int, addr: int) -> int:
        if name == ".":
            return addr
        self.used.add(name)
        if name in self.labels:
            return self.labels[name][0]
        if name in self.constants:
            if self.visible_constants is None or self.constant_order[name] < self.visible_constants:
                return self.constants[name]
            raise AsmError("symbol", f"'{name}' is used before its .equ", col, width,
                           f"it's defined on line {self.defined_on[name].number}")
        if name in isa.PREDEFINED_SYMBOLS:
            return isa.PREDEFINED_SYMBOLS[name]
        if name in self.aliases:
            raise AsmError("syntax", f"'{name}' is a register, not a value", col, width)
        hint = suggest(name, [*self.labels, *self.constants, *isa.PREDEFINED_SYMBOLS])
        raise AsmError("symbol", f"undefined symbol '{name}'", col, width,
                       f"did you mean '{hint}'?" if hint else None)

    # Pass 2: encode and place.

    def second_pass(self) -> None:
        too_big = None
        for stmt in self.statements:
            self.visible_constants = stmt.constants_known
            try:
                stmt.words = self.encode(stmt)
            except AsmError as err:
                self.report(stmt.line, err)
                continue
            end = stmt.addr + len(stmt.words)
            if end > isa.ROM_WORDS:
                too_big = too_big or (stmt, end)
                too_big = (too_big[0], max(too_big[1], end))
            try:
                self.place(stmt)
            except AsmError as err:
                self.report(stmt.line, err)
        if too_big:
            stmt, end = too_big
            self.report(stmt.line, AsmError("size", f"needs {end} words; ROM holds {isa.ROM_WORDS}"))

    def encode(self, stmt: Statement) -> list[int]:
        if stmt.is_word:
            words = [check_range(self.evaluate(op, stmt.addr), WORD_RANGE, op) & 0xFFFF
                     for op in stmt.operands]
            for op, word in zip(stmt.operands, words):
                if isa.decode(word)[0].hardware_only:
                    self.warn(stmt.line, AsmError("int_word", f"0x{word:04X} decodes as an INT word",
                                                  op.col, len(op.text),
                                                  "executing it re-enters the handler forever"))
            return words
        if stmt.form is None:
            return []
        values = tuple(self.operand_value(kind, payload, op, stmt.addr)
                       for kind, (_, payload, op) in zip(stmt.form.operands, stmt.operands))
        # Past-the-end statements are never placed; wrap so BRAINROT's `.` still encodes.
        return isa.encode(stmt.form, values, stmt.addr % isa.ROM_WORDS)

    def operand_value(self, kind: str, payload, op: Operand, addr: int):
        if SYNTAX[kind] != "expr":
            return payload
        bounds = K_RANGE if kind == "K" else ADDRESS_RANGE
        return check_range(self.evaluate(op, addr), bounds, op)

    def place(self, stmt: Statement) -> None:
        for addr in range(stmt.addr, min(stmt.addr + len(stmt.words), isa.ROM_WORDS)):
            if addr in self.owner:
                raise AsmError("overlap", f"two things at 0x{addr:02X} "
                                          f"(lines {self.owner[addr].number} and {stmt.line.number})")
        for addr, word in enumerate(stmt.words, stmt.addr):
            if addr < isa.ROM_WORDS:
                self.owner[addr] = stmt.line
                self.words[addr] = word

    # Checks.

    def check_warnings(self) -> None:
        for name, (_, line, col) in self.labels.items():
            if name not in self.used:
                self.warn(line, AsmError("unused", f"label '{name}' is never used", col, len(name)))
        self.check_vectors()
        self.check_handler_yaps()

    def with_form(self, slang: str) -> list[Statement]:
        return [s for s in self.statements if s.form is not None and s.form.slang == slang and s.words]

    def check_vectors(self) -> None:
        doomscrolls = self.with_form("DOOMSCROLL")
        if not doomscrolls:
            return
        for name, vector in isa.VECTORS.items():
            if vector and self.words[vector] == 0:
                self.warn(doomscrolls[0].line, AsmError(
                    "vector", f"vector 0x{vector:02X} ({name}) is CHILL but DOOMSCROLL turns interrupts on",
                    hint="put WEREBACK in unused vectors"))

    def handler_addresses(self) -> dict[int, str]:
        handlers = {}
        jump = isa.form("BET", "target").opcode
        for name, vector in isa.VECTORS.items():
            word = self.words[vector]
            if not vector or vector not in self.owner or word >> 11 != jump:
                continue
            addr = word & 0xFF
            while addr in self.owner and self.words[addr] != WEREBACK_WORD:
                handlers.setdefault(addr, name)
                addr += 1
        return handlers

    def check_handler_yaps(self) -> None:
        handlers = self.handler_addresses()
        for stmt in self.with_form("YAP"):
            if stmt.addr in handlers:
                self.warn(stmt.line, AsmError("yap", f"YAP inside the {handlers[stmt.addr]} handler",
                                              hint="it takes 2n + 2 cycles with interrupts off"))


def assemble(path: Path | str, source: str | None = None, werror: bool = False) -> Program:
    """Assemble a file. Pass `source` to assemble text that isn't on disk (includes still resolve from `path`)."""
    path = Path(path)
    asm = Assembler(werror)
    text = path.read_text() if source is None else source
    asm.read_file(path, str(path), text, (path.resolve(),))
    asm.second_pass()
    if not any(d.severity == "error" for d in asm.diagnostics):
        asm.check_warnings()
    labels = {name: addr for name, (addr, _, _) in asm.labels.items()}
    return Program(asm.words, asm.statements, labels, asm.diagnostics)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cook", description="Assemble AURA-8 source into a ROM image.")
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="hex file to write (.lst and .sym go next to it)")
    parser.add_argument("--format", choices=("raw", "plain"), default="raw")
    parser.add_argument("--boring", action="store_true", help="plain error messages, no roasts")
    parser.add_argument("-W", dest="warnings", choices=("error",), help="-W error: treat warnings as errors")
    args = parser.parse_args(argv)
    try:
        program = assemble(args.source, werror=args.warnings == "error")
    except OSError as err:
        print(f"cook: can't read {args.source}: {err.strerror}", file=sys.stderr)
        return 1
    for diagnostic in program.diagnostics:
        print(diagnostic.format(args.boring), file=sys.stderr)
    if program.failed:
        return 1
    hex_path = args.output or args.source.with_suffix(".hex")
    hex_path.parent.mkdir(parents=True, exist_ok=True)
    hex_path.write_text(format_hex(program.words, args.format))
    hex_path.with_suffix(".lst").write_text(program.listing())
    hex_path.with_suffix(".sym").write_text(program.symbol_table())
    used = len({a for s in program.statements for a in range(s.addr, s.addr + len(s.words))})
    print(f"cooked {args.source} -> {hex_path} ({used} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
