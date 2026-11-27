"""frfr: the AURA-8 test runner (SPEC §13)."""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cook
import twin

DEFAULT_CYCLES = 100_000
NUMBER = r"(0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+)"
STRING = r'"((?:[^"\\]|\\.)*)"'
DIRECTIVES = {
    "cycles": re.compile(rf"cycles\s+{NUMBER}$"),
    "key": re.compile(rf"key\s+{NUMBER}\s+{STRING}$"),
    "button": re.compile(rf"button\s+{NUMBER}\s+{NUMBER}$"),
    "halted": re.compile(r"expect\s+halted$"),
    "chat": re.compile(r"expect\s+chat\s*==\s*\[([^\]]*)\]$"),
    "tty": re.compile(rf"expect\s+tty\s*==\s*{STRING}$"),
    "mem": re.compile(rf"expect\s+mem\[\s*{NUMBER}\s*\]\s*==\s*{NUMBER}$"),
    "scalar": re.compile(rf"expect\s+(R[0-7]|hex|leds|vibes|cycles|exit)\s*==\s*{NUMBER}$"),
}


@dataclass
class Spec:
    cycles: int = DEFAULT_CYCLES
    keys: dict[int, str] = field(default_factory=dict)
    buttons: dict[int, int] = field(default_factory=dict)
    expects: list[tuple[str, object]] = field(default_factory=list)


def number(text: str) -> int:
    return int(text, 0)


def parse(source: str) -> Spec | None:
    """Read `; frfr:` lines; None means the file isn't a test."""
    spec, seen = Spec(), False
    for lineno, line in enumerate(source.splitlines(), 1):
        directive = re.match(r"\s*;\s*frfr:\s*(.*?)\s*$", line)
        if not directive:
            continue
        seen = True
        text = directive.group(1)
        kind, match = next(((k, m) for k, r in DIRECTIVES.items() if (m := r.match(text))), (None, None))
        try:
            if kind == "cycles":
                spec.cycles = number(match[1])
            elif kind == "key":
                cycle = number(match[1])
                spec.keys[cycle] = spec.keys.get(cycle, "") + cook.unescape(match[2], 1)
            elif kind == "button":
                spec.buttons[number(match[1])] = number(match[2])
            elif kind == "halted":
                spec.expects.append(("halted", True))
            elif kind == "chat":
                spec.expects.append(("chat", [number(v) for v in match[1].replace(",", " ").split()]))
            elif kind == "tty":
                spec.expects.append(("tty", cook.unescape(match[1], 1)))
            elif kind == "mem":
                spec.expects.append((f"mem[0x{number(match[1]):02X}]", number(match[2])))
            elif kind == "scalar":
                spec.expects.append((match[1], number(match[2])))
            else:
                raise ValueError
        except (ValueError, cook.AsmError):
            raise ValueError(f"line {lineno}: can't read frfr directive '{text}'") from None
    return spec if seen else None


def actual(tw: twin.Twin, target: str):
    if target == "halted":
        return tw.status in ("halted", "asleep")
    if target == "exit":
        return twin.EXIT_CODES[tw.status]
    if target == "tty":
        return tw.tty.decode("latin-1")
    if target == "cycles":
        return tw.cycle
    if target.startswith("R"):
        return tw.regs[int(target[1])]
    if target.startswith("mem["):
        return tw.peek(int(target[4:-1], 16))
    return getattr(tw, target)


def show(value) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        return repr(value)
    return f"0x{value:02X} ({value})"


def check(path: Path) -> list[str] | None:
    """Return failure messages, or None if the file has no frfr lines."""
    source = path.read_text()
    spec = parse(source)
    if spec is None:
        return None
    program = cook.assemble(path, source=source)
    if program.failed:
        return [d.format() for d in program.diagnostics if d.severity == "error"]
    tw = twin.Twin(program.words, spec.keys, spec.buttons)
    tw.run(spec.cycles)
    failures = [f"{target}: expected {show(expected)}, got {show(got)}"
                for target, expected in spec.expects if (got := actual(tw, target)) != expected]
    if failures:
        failures.append(tw.outcome())
    return failures


def test_files(paths: list[Path]) -> list[Path]:
    return [f for p in paths for f in (sorted(p.rglob("*.aura")) if p.is_dir() else [p])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frfr", description="Run AURA-8 programs against their frfr expectations.")
    parser.add_argument("paths", type=Path, nargs="+", help="test files or directories")
    args = parser.parse_args(argv)
    passed = failed = 0
    for path in test_files(args.paths):
        try:
            failures = check(path)
        except (OSError, ValueError) as err:
            failures = [str(err)]
        if failures is None:
            continue
        if failures:
            failed += 1
            print(f"FAIL (cap detected)  {path}")
            print("\n".join(f"    {line}" for f in failures for line in f.splitlines()))
        else:
            passed += 1
            print(f"PASS frfr  {path}")
    print(f"{passed} passed, {failed} failed")
    return 1 if failed or not passed else 0


if __name__ == "__main__":
    sys.exit(main())
