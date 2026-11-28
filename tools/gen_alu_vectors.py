import argparse
import random
import sys
from pathlib import Path

import isa
from twin import alu

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "hw" / "alu_vectors.txt"
HEADERS = {"logisim": "A[8] B[8] op[4] Cin Zin R[8] Z N V C", "digital": "A B op Cin Zin R Z N V C"}
EDGES = (0x00, 0x01, 0x7F, 0x80, 0xFF)
BINARY_OPS = range(isa.ALU["INC"])
UNARY_OPS = range(isa.ALU["INC"], len(isa.ALU_OPS))


def vector(op: int, a: int, b: int, cin: int, zin: int) -> str:
    result, flags = alu(op, a, b, cin | zin << 1)
    mask = isa.flag_mask(op)
    out = [str(flags >> isa.FLAG_BITS[f] & 1) if mask >> isa.FLAG_BITS[f] & 1 else "x" for f in "ZNVC"]
    return f"0x{a:02X} 0x{b:02X} 0x{op:X} {cin} {zin} 0x{result:02X} {' '.join(out)}"


def cases(count: int, seed: int):
    for op in UNARY_OPS:
        for a in range(256):
            for cin in (0, 1):
                yield op, a, 0, cin, 0
    for op in BINARY_OPS:
        for a in EDGES:
            for b in EDGES:
                for cin in (0, 1):
                    for zin in (0, 1):
                        yield op, a, b, cin, zin
    rng = random.Random(seed)
    for _ in range(count):
        yield rng.choice(BINARY_OPS), rng.randrange(256), rng.randrange(256), rng.randrange(2), rng.randrange(2)


def vectors(count: int = 5000, seed: int = 0, fmt: str = "logisim") -> str:
    ops = " ".join(f"{i:X}={name}" for i, name in enumerate(isa.ALU_OPS))
    lines = [f"# AURA-8 ALU vectors from twin; x = flag not written by that op. op: {ops}", HEADERS[fmt]]
    lines += [vector(*case) for case in cases(count, seed)]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_alu_vectors", description="Write ALU test vectors from twin's ALU.")
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--random", type=int, default=5000, metavar="N", help="random binary-op cases")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--format", choices=HEADERS, default="logisim")
    args = parser.parse_args(argv)
    text = vectors(args.random, args.seed, args.format)
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    except OSError as e:
        print(f"gen_alu_vectors: can't write {args.out}: {e.strerror}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({text.count(chr(10)) - 2} vectors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
