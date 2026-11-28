import argparse
import sys
from pathlib import Path

import isa

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "hw" / "control.hex"
WORDS_PER_LINE = 8


def control_hex() -> str:
    words = [f"{c.word:06x}" for c in isa.control_rom()]
    rows = [" ".join(words[i:i + WORDS_PER_LINE]) for i in range(0, len(words), WORDS_PER_LINE)]
    return "v2.0 raw\n" + "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_control", description="Build the decoder ROM image from isa.py.")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="fail if the image on disk is out of date")
    args = parser.parse_args(argv)
    text = control_hex()
    if args.check:
        try:
            current = args.out.read_text()
        except (OSError, UnicodeDecodeError) as e:
            print(f"gen_control: can't read {args.out}: {e}", file=sys.stderr)
            return 1
        if current != text:
            print(f"gen_control: {args.out} is out of date; run tools/gen_control.py", file=sys.stderr)
            return 1
        return 0
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    except OSError as e:
        print(f"gen_control: can't write {args.out}: {e.strerror}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({isa.ROM_WORDS} x {isa.CONTROL_WORD_BITS}-bit words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
