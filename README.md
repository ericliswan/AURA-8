# AURA-8

An 8-bit CPU built from logic gates up, with a slang instruction set: `RET` is `ITSOVER`, `RETI` is `WEREBACK` and `HALT` is `TOUCHGRASS`.

```asm
main:   SIXSEVEN  R0         ; LDI  R0, 67
        STASH     R0         ; PUSH R0
        HITUP     flex       ; CALL flex
        TOUCHGRASS           ; HALT
flex:   ITSOVER              ; RET  (it's so over)
```

The CPU is built in a logic simulator (Logisim-evolution or Digital), and a Python toolchain serves as the golden model: the circuit is tested against the emulator bit for bit and cycle for cycle. The design is AVR-shaped (same flag rules, stack convention and interrupt behaviour), so it doubles as ATmega practice. Every instruction also has a boring alias like `RET` or `HALT`.

The full design lives in [SPEC.md](SPEC.md).

## At a glance

| | |
|---|---|
| Data width | 8 bits |
| Instructions | 16 bits, fixed width, single-cycle |
| Architecture | Harvard: 256 × 16-bit program ROM, 256 bytes of data memory |
| Registers | R0–R7, plus PC, SP and VIBES (the status register) |
| ISA | 32 opcodes, 41 mnemonics, 7 pseudo-instructions |
| Interrupts | Timer, buttons and keyboard, vectored and prioritised |
| I/O | LEDs, buttons, hex display, terminal, keyboard, 8×8 LED matrix, timer, random numbers |

## A taste

Every Fibonacci number that fits in a byte, sent to the CHAT debug port:

```asm
; frfr: expect chat == [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233]
; frfr: expect halted
.org 0x00
        BET main
        WEREBACK
        WEREBACK
        WEREBACK
main:   MANIFEST  R0, 0       ; a
        MANIFEST  R1, 1       ; b
loop:   POST      CHAT, R0    ; say a
        LARP      R2, R0
        AURA      R2, R1      ; c = a + b
        FUMBLED   done        ; carried out, so c > 255: stop
        LARP      R0, R1      ; a = b
        LARP      R1, R2      ; b = c
        BET       loop
done:   POST      CHAT, R1    ; the last one that fit
        TOUCHGRASS
```

The `; frfr:` lines are test expectations, so every program is also its own test.

## Toolchain

All tools are Python 3.11+ with the standard library only.

| Tool | Job |
|---|---|
| `cook` | Assembler: `.aura` to `.hex` (Logisim ROM image), `.lst` and `.sym` |
| `uncook` | Disassembler |
| `twin` | Emulator and debugger, with cycle traces and a live LED panel |
| `frfr` | Test runner ("for real, for real") |

```sh
python tools/cook.py programs/fib.aura    # writes fib.hex, fib.lst, fib.sym
python tools/twin.py programs/fib.hex     # run it
python tools/twin.py programs/fib.hex --trace | head -20
python tools/frfr.py tests/               # PASS frfr / FAIL (cap detected)
```

## Roadmap

Software first, so there's always a known-good answer to test against. Then the hardware in slices, each of which runs real programs.

- [x] **M0** Golden model: `isa.py`, `cook`, `twin`, `frfr`
- [ ] **M1** ALU
- [ ] **M2** PC, ROM, register file, decoder, ALU writeback
- [ ] **M3** Status flags and branches
- [ ] **M4** Data memory and basic I/O
- [ ] **M5** Stack and subroutines
- [ ] **M6** Interrupts and the rest of I/O
- [ ] **M7** LED matrix and the capstone game, Tax Dodge
- [ ] **M8** Ship it

## Layout

| Path | Contents |
|---|---|
| `hw/` | The circuit |
| `tools/` | `isa.py` (the single ISA definition), the toolchain, and the control ROM and ALU test-vector generators |
| `programs/` | Example programs and Tax Dodge |
| `tests/isa/` | One small test per instruction |
| `tests/programs/` | Whole-program tests |

## Requirements

- Python 3.11+
- Logisim-evolution or Digital

## License

[GPL-3.0](LICENSE). Copyright (C) 2026 ericliswan.
