import argparse
import signal
import sys
from pathlib import Path

import isa
from twin import read_hex, read_sym


def listing(words: list[int], symbols: dict[int, str], boring: bool = False) -> str:
    lines = []
    for addr, word in enumerate(words):
        if addr in symbols:
            lines.append(f"{symbols[addr]}:")
        lines.append(f"{addr:02X}  {word:04X}  {isa.disassemble(word, addr, symbols, boring)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uncook", description="Disassemble an AURA-8 .hex file.")
    parser.add_argument("hex", type=Path)
    parser.add_argument("--sym", type=Path)
    parser.add_argument("--boring", action="store_true")
    args = parser.parse_args(argv)
    try:
        words = read_hex(args.hex)
        symbols = read_sym(args.sym) if args.sym else {}
    except (OSError, ValueError, UnicodeDecodeError) as e:
        print(f"uncook: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(listing(words, symbols, args.boring))
    return 0


if __name__ == "__main__":
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    sys.exit(main())
