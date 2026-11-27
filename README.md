# AURA-8

An 8-bit CPU built from logic gates up, with a slang instruction set. The full design is in [SPEC.md](SPEC.md).

## Layout

| Path | Contents |
|---|---|
| `hw/` | The circuit (Logisim-evolution or Digital) |
| `tools/` | `isa.py` (the single ISA definition), `cook` assembler, `uncook` disassembler, `twin` emulator, `frfr` test runner, ROM and test-vector generators |
| `programs/` | Example programs and the Tax Dodge capstone |
| `tests/isa/` | One small test per instruction |
| `tests/programs/` | Whole-program tests |

## Requirements

- Python 3.11+ (standard library only)
- Logisim-evolution or Digital for the hardware
