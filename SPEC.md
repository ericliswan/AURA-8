# AURA-8: a slang CPU

> An 8-bit CPU you build from logic gates up, with a slang instruction set: `RET` is `ITSOVER`, `RETI` is `WEREBACK` and `HALT` is `TOUCHGRASS`.

**Spec version:** 1.0 · **Hardware:** Logisim-evolution or Digital · **Tools:** Python 3.11+, standard library only

---

## Contents

0. [At a glance](#0-at-a-glance)
1. [Goals and non-goals](#1-goals-and-non-goals)
2. [Deliverables and repo layout](#2-deliverables-and-repo-layout)
3. [Programmer's model](#3-programmers-model)
4. [Instruction encoding](#4-instruction-encoding)
5. [Instruction reference](#5-instruction-reference)
6. [Flags in detail](#6-flags-in-detail)
7. [Stack, subroutines and the Rizz ABI](#7-stack-subroutines-and-the-rizz-abi)
8. [Interrupts](#8-interrupts)
9. [Memory-mapped I/O](#9-memory-mapped-io)
10. [Microarchitecture (the hardware build)](#10-microarchitecture-the-hardware-build)
11. [Assembler: `cook`](#11-assembler-cook)
12. [Emulator: `twin`](#12-emulator-twin)
13. [Testing: `frfr`](#13-testing-frfr)
14. [Example programs](#14-example-programs)
15. [Milestones](#15-milestones)
16. [Stretch goals (aura farming)](#16-stretch-goals-aura-farming)
17. [CSSE2010 map and exam drills](#17-csse2010-map-and-exam-drills)
18. [Differences from AVR](#18-differences-from-avr)
19. [Glossary](#19-glossary)
20. [Decisions you might want to change](#20-decisions-you-might-want-to-change)

---

## 0. At a glance

| | |
|---|---|
| Data width | 8 bits |
| Instruction width | 16 bits, fixed: every instruction is exactly one word |
| Architecture | Harvard (separate program ROM and data RAM), like AVR |
| Registers | R0–R7 general purpose, plus PC, SP and VIBES (the status register) |
| Program memory | 256 × 16-bit ROM |
| Data memory | 256 bytes: 240 bytes of RAM + 16 memory-mapped I/O registers |
| Execution | Single-cycle: every instruction, and every interrupt entry, takes exactly 1 clock |
| ISA | 32 opcodes, 41 mnemonics, 7 pseudo-instructions |
| Interrupts | 3 sources (timer, buttons, keyboard), vectored and prioritised |
| I/O | LEDs, buttons, 2-digit hex display, terminal, keyboard, 8×8 LED matrix, timer, random numbers, debug port |
| Tools | `cook` (assembler), `uncook` (disassembler), `twin` (emulator and debugger), `frfr` (test runner) |
| Source files | `.aura` |

The whole joke in five lines:

```asm
main:   SIXSEVEN R0          ; LDI  R0, 67
        STASH     R0          ; PUSH R0
        HITUP    flex        ; CALL flex
        TOUCHGRASS           ; HALT
flex:   ITSOVER              ; RET  (it's so over)
```

---

## 1. Goals and non-goals

**Goals**

1. Build a working CPU out of gates, registers, multiplexers and memories in a logic simulator, and understand every wire in it.
2. Cover most of CSSE2010 in one project: number representation, combinational and sequential logic, memory and address decoding, instruction encoding, assembly, the stack, interrupts, I/O and assembling. §17 maps each topic to the part of the build where it shows up.
3. Make it **AVR-shaped** wherever that doesn't cost much: same flag rules, same stack convention, same interrupt behaviour. That way the build doubles as ATmega exam prep. Every place it deliberately differs from AVR is listed in §18.
4. Be funny. Every mnemonic is slang, and every mnemonic also has a boring alias.
5. Keep software and hardware in agreement, bit for bit and cycle for cycle. The Python emulator is the golden model, and the circuit is tested against it.

**Non-goals**

- Speed, pipelining (that's a stretch goal), real timing analysis.
- A C compiler (also a stretch goal).
- Self-modifying code. Program memory is ROM, so it's impossible by design (Harvard!).
- Anything you hand in for CSSE2010. Keep this project separate from assignment work, and don't publish anything that overlaps an assignment spec.

---

## 2. Deliverables and repo layout

```
aura-8/
├── SPEC.md                  this document
├── README.md                demo GIF, how to run everything
├── hw/
│   └── aura8.circ        top level + subcircuits (aura8.dig if you use Digital)
├── tools/
│   ├── isa.py               the ONLY place the ISA is defined
│   ├── cook.py              assembler      .aura -> .hex + .lst + .sym
│   ├── uncook.py            disassembler   .hex -> readable listing
│   ├── twin.py              emulator + debugger (the golden model)
│   ├── gen_control.py       builds the decoder ROM image from isa.py
│   ├── gen_alu_vectors.py   builds ALU test vectors from twin's ALU
│   └── frfr.py              test runner
├── programs/                hello.aura, fib.aura, math.aura, tick.aura, dodge.aura
└── tests/
    ├── isa/                 one small test per instruction
    └── programs/            whole-program tests
```

**Single source of truth.** `isa.py` holds one table describing every instruction: mnemonic, boring alias, opcode, format, operand patterns, ALU operation, flags written and a one-line description. The assembler, disassembler, emulator, control-ROM generator and test generators all import it. Renaming a mnemonic is a one-line change, and the hardware decoder can't drift out of sync with the tools.

---

## 3. Programmer's model

### 3.1 Registers

| Register | Width | Notes |
|---|---|---|
| R0–R7 | 8 | General purpose. Every instruction works with every register. There's no AVR-style "R16 and up only" rule. |
| PC | 8 | Program counter: a word address into program ROM. Programs can't read it directly. |
| SP | 8 | Stack pointer. Points at the next **free** byte (AVR convention). Memory-mapped at `0xF1`. Resets to `0xEF`. |
| VIBES | 8 | Status register. Memory-mapped at `0xF0`. |

**VIBES layout**

| Bit | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| Flag | I | – | – | – | V | N | Z | C |

| Flag | Meaning | Nickname |
|---|---|---|
| I | Interrupts enabled | the vibe check |
| V | Signed (two's complement) overflow: the true answer didn't fit in −128..127 | crash-out flag |
| N | Negative: bit 7 of the result | negative aura |
| Z | Zero: the result was 0 | ghosted |
| C | Carry out of an add, or **borrow** out of a subtract | tax flag |

Bits 6–4 always read as 0, and writes to them are ignored.

### 3.2 Program memory

256 words × 16 bits, word-addressed, read-only while running.

| Address | Contents |
|---|---|
| `0x00` | Reset vector, usually `BET main` |
| `0x01` | TIMER interrupt vector |
| `0x02` | BUTTON interrupt vector |
| `0x03` | KEY interrupt vector |
| `0x04`–`0xFF` | Your program |

Each vector is a single instruction: normally `BET handler`, or `WEREBACK` if the vector is unused. Blank ROM is `0x0000`, which is `CHILL` (NOP), so an empty ROM just slides along harmlessly. PC wraps from `0xFF` to `0x00`.

The CPU can't read its own ROM as data, because Harvard keeps program and data memory separate. Text is printed with the `YAP` pseudo-instruction (§5.9) and constants are loaded with `MANIFEST`. The stretch goal `READTHEROOM` (§16) adds a way to read the ROM.

### 3.3 Data memory

256 bytes, byte-addressed.

| Range | What |
|---|---|
| `0x00`–`0xEF` | RAM, 240 bytes. Variables usually go at the bottom; the stack starts at the top (`0xEF`, called `RAMEND`) and grows down. |
| `0xF0`–`0xFF` | I/O registers (§9) |

RAM contents at reset are **undefined**. The emulator fills RAM with `0x00`, but programs must initialise anything they rely on.

### 3.4 Reset state

| State | Value after reset |
|---|---|
| PC | `0x00` |
| SP | `0xEF` |
| VIBES | `0x00` (so interrupts are off) |
| R0–R7 | `0x00` (defined so that hardware and emulator traces match) |
| IMASK, IFLAGS, TCTRL, TTOP, TCNT, timer prescaler | `0x00` |
| LEDS, HEX, MROW, all LED-matrix rows | `0x00` |
| DELULU (random generator state) | `0xA5` |
| Interrupt shadow (§8.4) | off |

---

## 4. Instruction encoding

### 4.1 Formats

Every instruction is one 16-bit word with the same three fields:

```
 15       11 10     8 7                      0
+-----------+--------+------------------------+
|  opcode   |   A    |        payload         |
+-----------+--------+------------------------+
```

| Format | Bits 15–11 | Bits 10–8 (A) | Bits 7–0 (payload) | Used by |
|---|---|---|---|---|
| R (register) | opcode | Rd or Ra | `bbb 00000`: register B in bits 7–5 | Register ALU ops, compares, LURK/POST through a pointer |
| I (immediate) | opcode | Rd or Ra | `K`: 8-bit constant, or `k`: 8-bit address | Immediate ALU ops, LURK/POST to a fixed address |
| J (jump) | opcode | `000` | `k`: target address | BET, HITUP |
| B (branch) | opcode | `ccc`: condition | `o`: signed 8-bit offset | The 8 branches |
| S (sub-op) | opcode | Rd or `000` | `00000 xxx`: sub-operation | SYS group, unary group |
| P (stack) | opcode | Ra or Rd | `00000000` | STASH, GRAB |

**Field legend used in the rest of this document**

| Symbol | Meaning |
|---|---|
| `ddd` | Rd, the destination register (field A) |
| `aaa` | Ra, a register being **read** from field A (the data register of POST and STASH) |
| `bbb` | Rb, the second register (field B, bits 7–5): a source operand or a memory pointer |
| `KKKKKKKK` | 8-bit constant (−128..255 accepted, stored as 8 bits) |
| `kkkkkkkk` | 8-bit address (0..255) |
| `oooooooo` | Branch offset (−128..127) |
| `ccc` | Branch condition |
| `xxx` | Sub-operation |

Unused bits must be 0. The assembler always writes 0 there, and the hardware ignores them.

### 4.2 Opcode map

Rows are bits 15–14 and columns are bits 13–11. For ALU instructions, the column **is** the ALU operation.

| 15–14 ↓ / 13–11 → | `000` ADD | `001` ADC | `010` SUB | `011` SBC | `100` AND | `101` OR | `110` XOR | `111` PASS |
|---|---|---|---|---|---|---|---|---|
| **`00`** | SYS group | STASH | VIBECHECK Rd, Rb | DOUBLECHECK | SUS Rd, Rb | GRAB | LURK Rd, [Rb] | POST [Rb], Ra |
| **`01`** | AURA Rd, Rb | AURAFARM Rd, Rb | TAX Rd, Rb | BACKTAX Rd, Rb | MUTUALS Rd, Rb | COLLAB Rd, Rb | BEEF Rd, Rb | LARP |
| **`10`** | BET | HITUP | VIBECHECK Rd, K | branch group | SUS Rd, K | LURK Rd, k | POST k, Ra | unary group |
| **`11`** | AURA Rd, K | AURAFARM Rd, K | TAX Rd, K | BACKTAX Rd, K | MUTUALS Rd, K | COLLAB Rd, K | BEEF Rd, K | MANIFEST |

**Design rules.** These rules keep the decoder small, and they're exactly the sort of thing an exam question pokes at.

1. **`0x0000` is `CHILL` (NOP)**, so blank ROM is harmless.
2. **Bit 15 means "the ALU's B input is the immediate."** Rows `01` and `11` differ only in this bit: `AURA R1, R2` versus `AURA R1, 5`, and `LARP` (MOV) versus `MANIFEST` (LDI).
3. **Bit 14 means "write the ALU result back to Rd."** In the ALU columns, rows `00` and `10` hold the same operations with writeback switched off. `VIBECHECK` is `TAX` that forgets the answer (CMP is SUB without writeback, just like on AVR). `DOUBLECHECK` is `BACKTAX` that forgets (CPC), and `SUS` is `MUTUALS` that forgets (TST).
4. **Bits 13–11 are the ALU operation** for every two-operand ALU instruction. Only the unary group takes its operation from somewhere else (bits 2–0).
5. **Column `111` in the ALU rows is PASS** (result = B), used by `LARP` and `MANIFEST`. PASS never changes flags, just like MOV and LDI on AVR.

### 4.3 Groups

**SYS group**, encoded `00000 000 00000 xxx`:

| `xxx` | Mnemonic | Word |
|---|---|---|
| `000` | CHILL | `0x0000` |
| `001` | TOUCHGRASS | `0x0001` |
| `010` | DOOMSCROLL | `0x0002` |
| `011` | LOCKIN | `0x0003` |
| `100` | ITSOVER | `0x0004` |
| `101` | WEREBACK | `0x0005` |
| `110` | BRUH | `0x0006` |
| `111` | IYKYK (boring name: INT): injected by hardware only, with the vector in bits 7–3 | `0x000F`, `0x0017`, `0x001F` |

**Unary group**, encoded `10111 ddd 00000 xxx`. The ALU operation is `1xxx`:

| `xxx` | `000` | `001` | `010` | `011` | `100` | `101` | `110` | `111` |
|---|---|---|---|---|---|---|---|---|
| Mnemonic | GLOWUP | FELLOFF | CRASHOUT | UNOREVERSE | LOWKEY | MID | SPIN | TRADE |
| ALU op | INC | DEC | COM | NEG | LSR | ASR | ROR | SWAP |

**Branch group**, encoded `10011 ccc oooooooo`. The conditions are in §5.6.

---

## 5. Instruction reference

**Notation.** Rd = R[`ddd`], Ra = R[`aaa`], Rb = R[`bbb`]. M[x] is the data-memory byte at x (RAM or I/O). `←` takes effect at the clock edge. The flags column lists the VIBES flags that change; `–` means none, and `Z*` means sticky Z (§6.3).

**Every instruction takes exactly one clock cycle.** Mnemonics are case-insensitive. The boring aliases (AVR names where AVR has one) are accepted by the assembler too (§11.5).

### 5.1 Data movement

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `MANIFEST Rd, K` | LDI | `11111 ddd KKKKKKKK` | Rd ← K | – |
| `LARP Rd, Rb` | MOV | `01111 ddd bbb 00000` | Rd ← Rb | – |
| `LURK Rd, k` | LDS | `10101 ddd kkkkkkkk` | Rd ← M[k] | – |
| `LURK Rd, [Rb]` | LD | `00110 ddd bbb 00000` | Rd ← M[Rb] | – |
| `POST k, Ra` | STS | `10110 aaa kkkkkkkk` | M[k] ← Ra | – (see note) |
| `POST [Rb], Ra` | ST | `00111 aaa bbb 00000` | M[Rb] ← Ra | – (see note) |

Note: posting to `VIBES` (`0xF0`) replaces every flag, including I.

### 5.2 Arithmetic

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `AURA Rd, Rb` | ADD | `01000 ddd bbb 00000` | Rd ← Rd + Rb | Z N V C |
| `AURA Rd, K` | ADDI † | `11000 ddd KKKKKKKK` | Rd ← Rd + K | Z N V C |
| `AURAFARM Rd, Rb` | ADC | `01001 ddd bbb 00000` | Rd ← Rd + Rb + C | Z N V C |
| `AURAFARM Rd, K` | ADCI † | `11001 ddd KKKKKKKK` | Rd ← Rd + K + C | Z N V C |
| `TAX Rd, Rb` | SUB | `01010 ddd bbb 00000` | Rd ← Rd − Rb | Z N V C |
| `TAX Rd, K` | SUBI | `11010 ddd KKKKKKKK` | Rd ← Rd − K | Z N V C |
| `BACKTAX Rd, Rb` | SBC | `01011 ddd bbb 00000` | Rd ← Rd − Rb − C | Z* N V C |
| `BACKTAX Rd, K` | SBCI | `11011 ddd KKKKKKKK` | Rd ← Rd − K − C | Z* N V C |
| `GLOWUP Rd` | INC | `10111 ddd 00000 000` | Rd ← Rd + 1 | Z N V (C unchanged) |
| `FELLOFF Rd` | DEC | `10111 ddd 00000 001` | Rd ← Rd − 1 | Z N V (C unchanged) |
| `UNOREVERSE Rd` | NEG | `10111 ddd 00000 011` | Rd ← 0 − Rd | Z N V C |

† Not a real AVR instruction. AVR fakes ADDI with SUBI and a negative constant.

### 5.3 Logic

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `MUTUALS Rd, Rb` | AND | `01100 ddd bbb 00000` | Rd ← Rd AND Rb | Z N, V ← 0 |
| `MUTUALS Rd, K` | ANDI | `11100 ddd KKKKKKKK` | Rd ← Rd AND K | Z N, V ← 0 |
| `COLLAB Rd, Rb` | OR | `01101 ddd bbb 00000` | Rd ← Rd OR Rb | Z N, V ← 0 |
| `COLLAB Rd, K` | ORI | `11101 ddd KKKKKKKK` | Rd ← Rd OR K | Z N, V ← 0 |
| `BEEF Rd, Rb` | EOR | `01110 ddd bbb 00000` | Rd ← Rd XOR Rb | Z N, V ← 0 |
| `BEEF Rd, K` | EORI † | `11110 ddd KKKKKKKK` | Rd ← Rd XOR K | Z N, V ← 0 |
| `CRASHOUT Rd` | COM | `10111 ddd 00000 010` | Rd ← NOT Rd | Z N, V ← 0, C ← 1 |
| `TRADE Rd` | SWAP | `10111 ddd 00000 111` | Rd ← Rd[3:0] : Rd[7:4] (swap nibbles) | – |

### 5.4 Shifts and rotates

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `LOWKEY Rd` | LSR | `10111 ddd 00000 100` | Shift right; 0 goes into bit 7 (unsigned ÷2) | Z, N ← 0, V, C ← old bit 0 |
| `MID Rd` | ASR | `10111 ddd 00000 101` | Shift right; bit 7 is kept (signed ÷2) | Z N V, C ← old bit 0 |
| `SPIN Rd` | ROR | `10111 ddd 00000 110` | Rotate right through carry: C goes into bit 7 | Z N V, C ← old bit 0 |
| `HIGHKEY Rd` | LSL | pseudo: `AURA Rd, Rd` | Shift left (×2) | Z N V C |
| `NIPS Rd` | ROL | pseudo: `AURAFARM Rd, Rd` | Rotate left through carry | Z N V C |

For the three real shifts, V = N XOR C after the shift, as on AVR. `NIPS` is `SPIN` spelled backwards, and it does the opposite thing.

### 5.5 Compare and test

These work out the flags and throw the result away.

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `VIBECHECK Rd, Rb` | CP | `00010 ddd bbb 00000` | flags ← Rd − Rb | Z N V C |
| `VIBECHECK Rd, K` | CPI | `10010 ddd KKKKKKKK` | flags ← Rd − K | Z N V C |
| `DOUBLECHECK Rd, Rb` | CPC | `00011 ddd bbb 00000` | flags ← Rd − Rb − C | Z* N V C |
| `SUS Rd, Rb` | TST † | `00100 ddd bbb 00000` | flags ← Rd AND Rb | Z N, V ← 0 |
| `SUS Rd, K` | TSTI † | `10100 ddd KKKKKKKK` | flags ← Rd AND K (test bits) | Z N, V ← 0 |
| `SUS Rd` | TST | pseudo: `SUS Rd, Rd` | Is it zero? Is it negative? | Z N, V ← 0 |

† AVR's TST only takes one register. The two-operand and immediate forms work like ARM's TST, and they're handy for checking one bit: `SUS R0, 0x80` then `CAP` means "branch if bit 7 is set".

### 5.6 Control flow

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `BET k` | JMP | `10000 000 kkkkkkkk` | PC ← k | – |
| `HITUP k` | CALL | `10001 000 kkkkkkkk` | M[SP] ← PC+1; SP ← SP−1; PC ← k | – |
| `ITSOVER` | RET | `0x0004` | SP ← SP+1; PC ← M[SP] | – |
| `WEREBACK` | RETI | `0x0005` | SP ← SP+1; PC ← M[SP]; I ← 1; shadow on | I |
| *branch* `k` | BRxx | `10011 ccc oooooooo` | if condition: PC ← PC + 1 + o | – |

**Branches.** The assembler computes o = k − (PC + 1). Because the whole address space is 8 bits, adding the 8-bit offset mod 256 already gives the right answer: sign extension is free, and every address is reachable from every branch.

| `ccc` | Slang | Boring | Taken when | After `VIBECHECK a, b` it means |
|---|---|---|---|---|
| `000` | `FR` | BREQ | Z = 1 | a = b |
| `001` | `CAP` | BRNE | Z = 0 | a ≠ b |
| `010` | `FUMBLED` | BRLO / BRCS | C = 1 | a < b, unsigned (or: an add carried out) |
| `011` | `SECURED` | BRSH / BRCC | C = 0 | a ≥ b, unsigned |
| `100` | `COOKED` | BRMI | N = 1 | The result was negative |
| `101` | `LETHIMCOOK` | BRPL | N = 0 | The result wasn't negative |
| `110` | `MOGGED` | BRLT | N XOR V = 1 | a < b, signed |
| `111` | `MOGGING` | BRGE | N XOR V = 0 | a ≥ b, signed |

Bits 2–1 of `ccc` choose a flag (Z, C, N or N XOR V) and bit 0 inverts it. In hardware that's a 4:1 mux and one XOR gate. As on AVR, there's no "greater than" branch: swap the operands instead (§6.4).

### 5.7 Stack

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `STASH Ra` | PUSH | `00001 aaa 00000000` | M[SP] ← Ra; SP ← SP−1 | – |
| `GRAB Rd` | POP | `00101 ddd 00000000` | SP ← SP+1; Rd ← M[SP] | – |

### 5.8 System

| Slang | Boring | Encoding | Operation | Flags |
|---|---|---|---|---|
| `CHILL` | NOP | `0x0000` | Nothing | – |
| `TOUCHGRASS` | HALT (like SLEEP) | `0x0001` | PC ← PC (stays on this instruction) | – |
| `DOOMSCROLL` | SEI | `0x0002` | I ← 1; shadow on (let the distractions in) | I |
| `LOCKIN` | CLI | `0x0003` | I ← 0 (no distractions) | I |
| `BRUH` | BREAK | `0x0006` | Hardware: same as CHILL, plus a debug LED. `twin`: breakpoint | – |

**`TOUCHGRASS`** stops the PC advancing.
- With I = 0 the CPU is finished until reset, and the emulator exits.
- With I = 1 interrupts still fire. INT pushes the address of the `TOUCHGRASS` itself, so after `WEREBACK` the CPU goes straight back to sleep. A main loop that only wakes up for interrupts is literally `DOOMSCROLL` then `TOUCHGRASS`.

### 5.9 Pseudo-instructions

The assembler expands these into real instructions.

| Pseudo | Expands to | Words | Boring |
|---|---|---|---|
| `HIGHKEY Rd` | `AURA Rd, Rd` | 1 | LSL |
| `NIPS Rd` | `AURAFARM Rd, Rd` | 1 | ROL |
| `GHOST Rd` | `BEEF Rd, Rd` | 1 | CLR (Z ← 1, N ← 0, V ← 0, C unchanged) |
| `MAXX Rd` | `MANIFEST Rd, 0xFF` | 1 | SER |
| `SIXSEVEN Rd` | `MANIFEST Rd, 67` | 1 | none. It loads 67. |
| `BRAINROT` | `BET .` | 1 | `RJMP PC`: an infinite loop. You're stuck scrolling forever. |
| `YAP "text"` | `STASH R7`, then for each character `MANIFEST R7, c` + `POST TTY, R7`, then `GRAB R7` | 2n + 2 | Prints a string. All registers and flags are preserved. |

`YAP` is expensive: `YAP "aura +1\n"` costs 18 of your 256 words. Yap responsibly.

---

## 6. Flags in detail

### 6.1 What each ALU operation does to the flags

R is the 8-bit result and A is the first operand. `–` means unchanged.

| ALU op | Used by | Z | N | V | C |
|---|---|---|---|---|---|
| `0000` ADD | AURA, HIGHKEY | R = 0 | R7 | signed overflow | carry out |
| `0001` ADC | AURAFARM, NIPS | R = 0 | R7 | signed overflow | carry out |
| `0010` SUB | TAX, VIBECHECK | R = 0 | R7 | signed overflow | borrow |
| `0011` SBC | BACKTAX, DOUBLECHECK | R = 0 **and** old Z | R7 | signed overflow | borrow |
| `0100` AND | MUTUALS, SUS | R = 0 | R7 | 0 | – |
| `0101` OR | COLLAB | R = 0 | R7 | 0 | – |
| `0110` XOR | BEEF, GHOST | R = 0 | R7 | 0 | – |
| `0111` PASS | LARP, MANIFEST | – | – | – | – |
| `1000` INC | GLOWUP | R = 0 | R7 | A was `0x7F` | – |
| `1001` DEC | FELLOFF | R = 0 | R7 | A was `0x80` | – |
| `1010` COM | CRASHOUT | R = 0 | R7 | 0 | 1 |
| `1011` NEG | UNOREVERSE | R = 0 | R7 | A was `0x80` | A ≠ 0 |
| `1100` LSR | LOWKEY | R = 0 | 0 | N XOR C | old bit 0 |
| `1101` ASR | MID | R = 0 | R7 | N XOR C | old bit 0 |
| `1110` ROR | SPIN | R = 0 | R7 | N XOR C | old bit 0 |
| `1111` SWAP | TRADE | – | – | – | – |

These match AVR, weird cases included. INC and DEC leave C alone, so loop counters don't wreck multi-byte arithmetic. COM sets C. NEG sets C unless the value was 0.

### 6.2 After a subtraction, C means borrow

The ALU subtracts by adding: A − B = A + NOT B + 1. The adder's carry-out is 1 when there was **no** borrow, so for SUB, SBC, NEG and the compares, the C flag stores **NOT carry-out**. Then C = 1 means "A was smaller than B (unsigned)". This is the AVR convention, and the opposite of 6502 and ARM, so it's a classic exam trap.

Subtract-with-carry works the same way: A − B − C = A + NOT B + NOT C.

### 6.3 Sticky Z (why DOUBLECHECK exists)

To compare two 16-bit numbers, compare the low bytes, then the high bytes minus the borrow:

```asm
; compare R1:R0 with R3:R2 (16-bit, unsigned)
        VIBECHECK   R0, R2     ; low bytes
        DOUBLECHECK R1, R3     ; high bytes, minus the borrow from the low bytes
        FR          same16     ; Z = 1 only if BOTH bytes matched
        FUMBLED     less16     ; C = 1 if R1:R0 < R3:R2
```

The sticky Z rule (Z ← (R = 0) AND old Z, for SBC, SBCI and CPC) is what makes `FR` correct here. Compare `0x1300` with `0x12FF`:

- Low bytes: `0x00 − 0xFF` borrows, so C = 1 and Z = 0.
- High bytes: `0x13 − 0x12 − 1 = 0x00`. Without sticky Z, Z would become 1 and `FR` would claim the numbers are equal. With sticky Z, Z = 1 AND 0 = 0. Correct.

The same pattern does 16-bit arithmetic:

```asm
        AURA     R0, R2        ; R1:R0 += R3:R2  (low byte first)
        AURAFARM R1, R3        ;                 (high byte, plus the carry)

        TAX R0, R2        ; R1:R0 -= R3:R2
        BACKTAX  R1, R3
```

### 6.4 Signed versus unsigned cheat sheet

After `VIBECHECK a, b`:

| You want | Unsigned | Signed |
|---|---|---|
| a = b | `FR` | `FR` |
| a ≠ b | `CAP` | `CAP` |
| a < b | `FUMBLED` | `MOGGED` |
| a ≥ b | `SECURED` | `MOGGING` |
| a > b | `VIBECHECK b, a` then `FUMBLED` | `VIBECHECK b, a` then `MOGGED` |
| a ≤ b | `VIBECHECK b, a` then `SECURED` | `VIBECHECK b, a` then `MOGGING` |

Worked example: a = `0x80`, b = `0x01`. Unsigned, 128 ≥ 1, so `SECURED` is taken. Signed, −128 < 1, so `MOGGED` is taken. The flags are Z = 0, N = 0, V = 1, C = 0: N is 0 because `0x80 − 0x01 = 0x7F`, and V is 1 because −128 − 1 = −129 doesn't fit in 8 bits.

---

## 7. Stack, subroutines and the Rizz ABI

### 7.1 How the stack works

SP points at the next **free** byte and the stack grows **down**, as on AVR.

- `STASH` writes first, then decrements SP.
- `GRAB` increments SP first, then reads.
- `HITUP` pushes the return address PC + 1. It's a single byte, because the PC is 8 bits. `ITSOVER` pops it.

Here's the start of `math.aura` (§14.3). `HITUP mul8` sits at address `0x06`, and `mul8` starts with `STASH R4`:

```
address   before        after HITUP mul8     after STASH R4
0xEF      <- SP         0x07  (return addr)  0x07
0xEE                    <- SP                saved R4
0xED                                         <- SP
```

### 7.2 The Rizz ABI (calling convention)

| Registers | Role | Who saves them |
|---|---|---|
| R0–R3 | Arguments (R0 first) and return values | The caller: a function may overwrite them |
| R4–R6 | Long-lived values | The callee: a function that uses them must save and restore them |
| R7 | Scratch. `YAP` uses it but puts it back. | The caller |

- 16-bit values live in a register pair, with the high byte in the higher register: `R1:R0`.
- Keep the stack balanced: every function returns with SP exactly where it found it.
- Interrupt handlers save **everything** they touch, including VIBES (§8.5).
- RAM is shared between your variables (from `0x00` up) and the stack (from `0xEF` down). Each call costs 1 byte plus whatever it pushes. `twin` warns you if SP wraps around into the I/O registers.

---

## 8. Interrupts

### 8.1 Sources

| IFLAGS bit | Source | Vector | Set when | Cleared by |
|---|---|---|---|---|
| 0 | TIMER | `0x01` | The timer count matches TTOP (§9.3) | Automatically on interrupt entry, or writing 1 to IFLAGS bit 0 |
| 1 | BUTTON | `0x02` | Any BUTTONS bit goes from 0 to 1 | Automatically on interrupt entry, or writing 1 to IFLAGS bit 1 |
| 2 | KEY | `0x03` | The keyboard has a character waiting. This is a **level**, not an event. | Reading KBD until the buffer is empty |

Priority: TIMER > BUTTON > KEY. The lowest vector wins, as on AVR.

### 8.2 When an interrupt is taken

At the start of every cycle the CPU computes:

```
pending = IFLAGS AND IMASK
take    = I AND (pending != 0) AND NOT shadow
```

If `take` is 1, the instruction just fetched is **thrown away**: it isn't executed and the PC doesn't move. In its place the hardware feeds the decoder an `INT` word for the highest-priority pending source.

### 8.3 What INT does (one cycle)

1. M[SP] ← PC, then SP ← SP − 1. That pushes the address of the instruction that was skipped, **not** PC + 1, so it runs after `WEREBACK`.
2. I ← 0
3. PC ← vector (1, 2 or 3)
4. The TIMER or BUTTON flag being serviced is cleared. KEY isn't cleared, because it's level-sensitive and stays set until KBD is empty.

### 8.4 The shadow

After `DOOMSCROLL` or `WEREBACK`, the next instruction **always** runs before another interrupt can be taken. AVR guarantees the same thing. Two consequences:

- `DOOMSCROLL` followed by `TOUCHGRASS` reliably gets to the sleep.
- A buggy handler that never clears its source can't starve `main` completely: main still gets one instruction between handler runs. (Checked on the prototype: a KEY handler that never reads KBD runs over and over, and main still runs one instruction each time.)

In hardware the shadow is a 1-bit register. `DOOMSCROLL` and `WEREBACK` set it, every other instruction clears it, and it blocks `take`.

### 8.5 Handler template: save VIBES!

The hardware doesn't save the flags, and neither does AVR. Suppose `main` has just done `SUS R1` and is about to `FR echo` when an interrupt arrives. If the handler changes Z, main takes the wrong branch after `WEREBACK`. That kind of bug only shows up once in a thousand runs. So:

```asm
on_timer:
        STASH  R0
        LURK  R0, VIBES      ; save the flags
        STASH  R0
        ;  ... handler body; R0 is free to use ...
        GRAB R0
        POST  VIBES, R0      ; restore the flags (I comes back as 0, that's fine)
        GRAB R0
        WEREBACK             ; RETI: return and set I
```

### 8.6 Nesting and latency

- I = 0 inside a handler, so interrupts don't nest. A handler may `DOOMSCROLL` to allow nesting, at its own risk.
- If an event sets its flag at the end of cycle *t*, the INT happens in cycle *t* + 1 at the earliest (if I = 1 and the shadow is off). The vector's `BET` runs in cycle *t* + 2 and the handler's first instruction in cycle *t* + 3. In `tick.aura` (§14.4), the timer matches at the end of cycle 799 and the INT happens in cycle 800.

---

## 9. Memory-mapped I/O

### 9.1 Register map

| Address | Name | Access | Reset | What it does |
|---|---|---|---|---|
| `0xF0` | VIBES | R/W | `0x00` | Status register (§3.1) |
| `0xF1` | SP | R/W | `0xEF` | Stack pointer |
| `0xF2` | LEDS | R/W | `0x00` | 8 LEDs; bit 7 is the leftmost |
| `0xF3` | BUTTONS | R | – | 8 buttons or switches; 1 = pressed |
| `0xF4` | HEX | R/W | `0x00` | Shown on two hex digits |
| `0xF5` | TTY | W | – | Writing a byte prints that ASCII character on the terminal |
| `0xF6` | KBD | R | – | Next keyboard character, `0x00` if none. **Reading removes it.** |
| `0xF7` | DELULU | R/W | `0xA5` | Pseudo-random byte. **Reading advances it.** |
| `0xF8` | TCTRL | R/W | `0x00` | Timer control: bit 0 = enable, bits 2–1 = prescaler |
| `0xF9` | TTOP | R/W | `0x00` | Timer compare value |
| `0xFA` | TCNT | R/W | `0x00` | Timer count |
| `0xFB` | MROW | W | `0x00` | LED matrix row select, 0–7 (0 = top) |
| `0xFC` | MDATA | W | – | Writes the selected matrix row (bit 7 = leftmost column) |
| `0xFD` | IMASK | R/W | `0x00` | Interrupt enables: bit 0 TIMER, bit 1 BUTTON, bit 2 KEY |
| `0xFE` | IFLAGS | R / write-1-to-clear | `0x00` | Pending interrupts (same bits). Writing 1 clears bits 0–1. Bit 2 is read-only: "KBD has data". |
| `0xFF` | CHAT | W | – | Debug port. `twin` prints `chat: 0x2A (42)`; in hardware, wire it to a third pair of hex digits or a probe. |

Write-only registers read as `0x00`. Writes to read-only registers are ignored.

### 9.2 Reads with side effects

Reading KBD or DELULU changes the device: it pops the keyboard buffer or advances the random generator. That means the hardware needs a **read-enable** signal (`mem_re`, §10.4), not just an address. Two reads of KBD in a row return two different characters. It's the same idea as reading AVR's UART data register.

### 9.3 Timer

- An 8-bit prescaler counts up every clock, always. Writes don't reset it.
- TCTRL bits 2–1 choose how often the timer **ticks**:

| TCTRL bits 2–1 | Tick every | TCTRL value with enable |
|---|---|---|
| `00` | 1 cycle | `0x01` |
| `01` | 8 cycles | `0x03` |
| `10` | 64 cycles | `0x05` |
| `11` | 256 cycles | `0x07` |

- On each tick (only while TCTRL bit 0 = 1): if TCNT = TTOP, then TCNT ← 0 and IFLAGS.TIMER ← 1; otherwise TCNT ← TCNT + 1. This is "clear timer on compare", like AVR's CTC mode.
- **Period = prescaler × (TTOP + 1) cycles.** For example, ÷8 with TTOP = 99 gives one interrupt every 800 cycles.

**Exact rules**, so that hardware and emulator agree cycle for cycle:
- A tick happens in a cycle where the prescaler's value at the **start** of the cycle has its low 3, 6 or 8 bits all set (for ÷8, ÷64 or ÷256). ÷1 ticks every cycle.
- If the CPU writes TCNT during a cycle, the write wins and no compare happens in that cycle.
- Writes to TCTRL and TTOP take effect from the next cycle.

### 9.4 Buttons

BUTTONS reads the live state of the buttons. A rising edge on any bit (0 at one clock edge, 1 at the next) sets IFLAGS.BUTTON. In hardware: register last cycle's BUTTONS, compute `rising = now AND NOT last`, and OR the 8 bits together. That's a textbook edge detector. Real buttons bounce; simulated ones don't. A debouncer is a stretch goal.

### 9.5 Keyboard and terminal

- **KBD** is a first-in, first-out buffer of ASCII characters. In hardware it's the simulator's keyboard component; in `twin` it's filled by `--key`. A read returns the oldest character and removes it; an empty buffer reads as `0x00`. IFLAGS bit 2 is 1 while characters are waiting.
- **TTY** prints each byte written to it. `0x0A` is a newline. Clearing the screen with `0x0C` is optional.

### 9.6 DELULU (random numbers)

DELULU is an 8-bit Galois linear-feedback shift register (LFSR). A read returns the current state; at the end of that cycle the state advances:

```
state <- (state >> 1) XOR (0xB8 if the old bit 0 was 1, else 0x00)
```

The mask `0xB8` is the polynomial x⁸ + x⁶ + x⁵ + x⁴ + 1, which is maximal length: the state visits all 255 non-zero values before repeating (checked). It resets to `0xA5`. Writing sets the state. Writing 0 stores 1 instead, because an LFSR at 0 is stuck there forever, which would be fully delulu.

It's deterministic on purpose: the same program with the same inputs gives the same "random" numbers on the circuit and in `twin`, so tests can compare them. For variety in games, seed it from TCNT when the player first presses a key.

### 9.7 LED matrix

There are 8 row registers, one byte per row. Write the row number to MROW, then the row's pixels to MDATA. Row 0 is the top and bit 7 is the leftmost column. The matrix shows all 8 registers continuously. Real hardware would multiplex the rows, which is a stretch goal.

### 9.8 HEX and CHAT

HEX drives two hex digit displays. CHAT is a debug output: put test results there, so test programs don't need the terminal.

---

## 10. Microarchitecture (the hardware build)

### 10.1 Overview

It's a **single-cycle Harvard** design. Within one clock cycle the CPU fetches an instruction, decodes it, reads registers, runs the ALU and reads or writes data memory. On the rising clock edge, every piece of state updates at once: PC, register file, SP, VIBES, RAM, I/O registers and the shadow bit. There are no multi-step sequences, so the control unit is purely combinational. A microcoded multi-cycle rebuild is a stretch goal (§16).

```
 +------+   +-----------+   +---------+   +---------+
 |  PC  |-->| prog ROM  |-->| IRQ mux |-->| decoder |--> control signals (10.4)
 +------+   | 256 x 16  |   +---------+   +---------+
    ^       +-----------+        |
    |                            |  instr:  A=[10:8]  B=[7:5]  imm8=[7:0]
    |                            v
    |                 +---------------------+
    |      WB mux --->|    register file    |
    |        ^        |  R0..R7, 2 read / 1 write
    |        |        +---------------------+
    |        |            | RA         | RB
    |        |            |       [B mux] <-- imm8
    |        |            v            v
    |        |        +---------------------+  flags  +-------+
    |        +--------|         ALU         |-------->| VIBES |
    |        |        +---------------------+         +-------+
    |        |
    |        |        +-------------------------------+
    |        +--------|  data memory: RAM + I/O       |<-- address: imm8 / RB / SP / SP+1
    |      read data  |  (0xF0-0xFF = I/O registers)  |<-- write data: RA / PC+1 / PC
    |                 +-------------------------------+
    |                                 ^
    |                          +-------------+
    |                          | SP (+1, -1) |
    |                          +-------------+
    |
    +-- next-PC mux: PC+1 | imm8 | PC+1+imm8 if taken | read data | PC | vector
```

### 10.2 Subcircuits

Build and test these one at a time before wiring the top level.

| Subcircuit | Inputs → outputs | Built from |
|---|---|---|
| `alu` | A[8], B[8], op[4], Cin, Zin → R[8], Z, N, V, C | Adder, input muxes, logic gates, result mux |
| `flagmask` | op[4] → which of Z, N, V, C to update | 16-row truth table (§6.1) |
| `regfile` | A[3], B[3], wdata[8], we, clk → RA[8], RB[8] | 8 registers, 3:8 decoder, two 8:1 muxes |
| `decoder` | opcode[5], sub[3] → 24 control bits | ROM (generated) or hand-made logic |
| `branch` | ccc[3], Z, C, N, V → take | 4:1 mux and one XOR |
| `pc_unit` | pc_sel, imm8, read data, vector, take → PC | Register, incrementer, 8-bit adder, mux |
| `stack_unit` | sp_op, SP-write from I/O → SP, SP+1 | Register, +1/−1, mux |
| `vibes` | ALU flags, mask, flags_we, i_set/i_clr, I/O write → VIBES | 5 flip-flops with input muxes |
| `mem_unit` | address mux, write-data mux, RAM, I/O bus, address decoder | Muxes, comparator, RAM |
| `io` | I/O bus → devices | Registers, timer counter, prescaler, LFSR, edge detector |
| `irq` | IFLAGS, IMASK, I, shadow, ROM word → instr, take, src | AND gates, priority encoder, mux |

### 10.3 Datapath, wire by wire

- **Fetch:** ROM[PC] goes through the `irq` mux, which substitutes the INT word when `take` = 1, and comes out as `instr`.
- **Fields:** opcode = instr[15:11], A = instr[10:8], B = instr[7:5], imm8 = instr[7:0], sub = instr[2:0].
- **Register reads:** RA = R[A], RB = R[B]. The write port always writes R[A].
- **ALU:** first operand = RA; second operand = `alu_b_sel` ? imm8 : RB.
- **Data address:** `addr_sel` picks imm8, RB, SP or SP+1.
- **Address decode:** `io` = (address[7:4] = `1111`). RAM write enable = `mem_we` AND NOT `io`. I/O register write enable = `mem_we` AND `io`, then a 4:16 decoder on address[3:0].
- **Write data:** `wdata_sel` picks RA, PC+1 or PC.
- **Read data:** `io` ? (I/O register addressed by address[3:0]) : RAM[address].
- **Writeback:** `wb_sel` picks the ALU result or the read data.
- **Next PC:** see §10.8.

### 10.4 Control signals

| Signal | Bits | Meaning |
|---|---|---|
| `reg_we` | 1 | Write R[A] at the clock edge |
| `wb_sel` | 1 | 0 = ALU result, 1 = data-memory read |
| `alu_b_sel` | 1 | 0 = RB, 1 = imm8 |
| `alu_op` | 4 | ALU operation (§6.1) |
| `flags_we` | 1 | Let the ALU update VIBES, masked per operation by `flagmask` |
| `addr_sel` | 2 | `00` imm8, `01` RB, `10` SP, `11` SP+1 |
| `mem_we` | 1 | Write data memory or I/O |
| `mem_re` | 1 | Read data memory or I/O. Needed for the KBD and DELULU side effects. |
| `wdata_sel` | 2 | `00` RA, `01` PC+1, `10` PC |
| `sp_op` | 2 | `00` hold, `01` SP−1, `10` SP+1 |
| `pc_sel` | 3 | `000` PC+1, `001` imm8, `010` branch, `011` read data, `100` PC (hold), `101` vector |
| `i_set` | 1 | I ← 1 |
| `i_clr` | 1 | I ← 0 |
| `shadow_set` | 1 | Shadow on for the next instruction |
| `int_ack` | 1 | Clear the TIMER or BUTTON flag being serviced |
| `brk` | 1 | BRUH: light the debug LED |

**Control word layout** (24 bits, for the decoder ROM):

| Bits | 23 | 22 | 21 | 20 | 19 | 18–16 | 15–14 | 13–12 | 11 | 10 | 9–8 | 7 | 6–3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Field | brk | int_ack | shadow_set | i_clr | i_set | pc_sel | sp_op | wdata_sel | mem_re | mem_we | addr_sel | flags_we | alu_op | alu_b_sel | wb_sel | reg_we |

For example, `AURA Rd, Rb` is `0x000081`, `MANIFEST` is `0x00003D` and `HITUP` is `0x015600`.

### 10.5 Control table

`–` means "don't care, use 0". Every field that's not listed is 0.

| Instruction | reg_we | wb | alu_b | alu_op | flags_we | addr | mem_we | mem_re | wdata | sp | pc | Also |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CHILL | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | PC+1 | |
| TOUCHGRASS | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | PC | |
| DOOMSCROLL | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | PC+1 | i_set, shadow_set |
| LOCKIN | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | PC+1 | i_clr |
| ITSOVER | 0 | – | – | – | 0 | SP+1 | 0 | 1 | – | +1 | read | |
| WEREBACK | 0 | – | – | – | 0 | SP+1 | 0 | 1 | – | +1 | read | i_set, shadow_set |
| BRUH | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | PC+1 | brk |
| INT (injected) | 0 | – | – | – | 0 | SP | 1 | 0 | PC | −1 | vector | i_clr, int_ack |
| STASH | 0 | – | – | – | 0 | SP | 1 | 0 | RA | −1 | PC+1 | |
| GRAB | 1 | mem | – | – | 0 | SP+1 | 0 | 1 | – | +1 | PC+1 | |
| VIBECHECK Rd, Rb | 0 | – | RB | SUB | 1 | – | 0 | 0 | – | hold | PC+1 | |
| DOUBLECHECK | 0 | – | RB | SBC | 1 | – | 0 | 0 | – | hold | PC+1 | |
| SUS Rd, Rb | 0 | – | RB | AND | 1 | – | 0 | 0 | – | hold | PC+1 | |
| LURK Rd, [Rb] | 1 | mem | – | – | 0 | RB | 0 | 1 | – | hold | PC+1 | |
| POST [Rb], Ra | 0 | – | – | – | 0 | RB | 1 | 0 | RA | hold | PC+1 | |
| AURA … BEEF Rd, Rb | 1 | ALU | RB | instr[13:11] | 1 | – | 0 | 0 | – | hold | PC+1 | |
| LARP | 1 | ALU | RB | PASS | 0 | – | 0 | 0 | – | hold | PC+1 | |
| BET | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | imm8 | |
| HITUP | 0 | – | – | – | 0 | SP | 1 | 0 | PC+1 | −1 | imm8 | |
| VIBECHECK Rd, K | 0 | – | imm | SUB | 1 | – | 0 | 0 | – | hold | PC+1 | |
| branch group | 0 | – | – | – | 0 | – | 0 | 0 | – | hold | branch | |
| SUS Rd, K | 0 | – | imm | AND | 1 | – | 0 | 0 | – | hold | PC+1 | |
| LURK Rd, k | 1 | mem | – | – | 0 | imm8 | 0 | 1 | – | hold | PC+1 | |
| POST k, Ra | 0 | – | – | – | 0 | imm8 | 1 | 0 | RA | hold | PC+1 | |
| unary group | 1 | ALU | – | `1` + instr[2:0] | 1 | – | 0 | 0 | – | hold | PC+1 | |
| AURA … BEEF Rd, K | 1 | ALU | imm | instr[13:11] | 1 | – | 0 | 0 | – | hold | PC+1 | |
| MANIFEST | 1 | ALU | imm | PASS | 0 | – | 0 | 0 | – | hold | PC+1 | |

The flags actually written = `flags_we` AND `flagmask(alu_op)`. So `TRADE` (SWAP) never touches flags even though `flags_we` = 1.

### 10.6 Decoder: two ways to build it

**Option A (recommended first): a control ROM.** Use a 256 × 24-bit ROM addressed by `{opcode, instr[2:0]}`. The sub-op bits only matter for the SYS and unary groups; every other opcode just repeats the same control word 8 times. `gen_control.py` builds the image from `isa.py`, so changing an instruction means regenerating the image, not rewiring.

**Option B (exam practice): hand-made logic.** Derive a few signals yourself with Karnaugh maps and check them against the ROM. `alu_b_sel` is just instr[15]. `reg_we` makes a good 5-variable K-map exercise (§17.2).

### 10.7 ALU

Seven operations share **one** 8-bit adder by muxing its inputs:

| op | Adder X | Adder Y | Carry in | C flag gets |
|---|---|---|---|---|
| ADD | A | B | 0 | carry out |
| ADC | A | B | C | carry out |
| SUB | A | NOT B | 1 | NOT carry out |
| SBC | A | NOT B | NOT C | NOT carry out |
| INC | A | `0x00` | 1 | unchanged |
| DEC | A | `0xFF` | 0 | unchanged |
| NEG | `0x00` | NOT A | 1 | NOT carry out |

**One overflow formula covers all seven:** V = (X7 = Y7) AND (R7 ≠ X7), using the adder's actual inputs. It works for subtraction because Y is already NOT B.

The rest:
- **Logic unit:** AND, OR, XOR, COM (NOT A), SWAP (nibbles), PASS (B).
- **Shifter:** LSR, ASR and ROR, each needing A and the incoming C.
- **Result mux:** selects by `alu_op`.
- **Z** = NOR of the 8 result bits, ANDed with the incoming Z for SBC. **N** = result bit 7. **V** for the shifts = N XOR (new C).

### 10.8 Register file, PC, SP, VIBES

- **Register file:** 8 × 8-bit registers. Writing: a 3:8 decoder on A, ANDed with `reg_we`, drives each register's enable. Reading: two 8:1 multiplexers, selected by A and B.
- **Next PC:** a mux on `pc_sel`. The branch source is `take ? (PC+1) + imm8 : PC+1`, where `take` = mux4(ccc[2:1]; Z, C, N, N XOR V) XOR ccc[0]. The vector source is `000` followed by instr[7:3].
- **SP:** next SP = (POST to `0xF1`) ? write data : (`sp_op` = −1 ? SP−1 : `sp_op` = +1 ? SP+1 : SP). SP+1 also feeds the address mux.
- **VIBES:** for each of Z, N, V and C: if POST to `0xF0`, take the write data's bit; else if (`flags_we` AND mask bit), take the ALU flag; else hold. For I: `i_set` → 1, `i_clr` → 0, POST to `0xF0` → write data bit 7, else hold.

### 10.9 Interrupt controller

```
pending = IFLAGS[2:0] AND IMASK[2:0]
take    = I AND NOT shadow AND (pending != 0)
src     = priority_encoder(pending)              ; bit 0 wins
vector  = src + 1                                ; 1, 2 or 3
instr   = take ? (00000 000 vvvvv 111) : ROM[PC] ; vvvvv = vector
```

The INT word then goes through the normal decoder like any other instruction: one more row in the control table, no special sequencing.

### 10.10 Practical build notes (and gotchas)

1. **One clock for everything.** Never put logic on the clock line; use enables instead.
2. **RAM reads must be combinational.** The read value has to appear in the same cycle, with writes on the clock edge, or single-cycle `LURK` and `ITSOVER` break. Check your simulator's RAM options (in Logisim-evolution, the RAM's data-interface setting) and confirm with a one-instruction test.
3. **Non-zero reset values.** Simulator registers reset to 0. Store `SP XOR 0xEF` in the SP register (and `state XOR 0xA5` in the LFSR), and XOR again on the way out. Now the all-zero reset means SP = `0xEF`.
4. **Combinational loops** cause "oscillation apparent" errors. The usual culprit is read data feeding back into the address, or a loop through flags → branch → PC → ROM. Every path must pass through a register.
5. **Edge-set flags beat clears.** If a timer match and a clear of IFLAGS happen in the same cycle, the flag stays set. Otherwise events get lost.
6. **Debug outputs pay for themselves:** PC and instr on hex displays, a "TOUCHING GRASS" LED (halted), a BRUH LED and a single-step clock button.
7. **Simulated clocks are slow,** typically in the kHz range in a logic simulator. Pick TTOP and the prescaler for the speed you actually get. `twin` runs far faster.

---

## 11. Assembler: `cook`

*Let him cook.*

### 11.1 Usage

```
cook programs/fib.aura                   # writes fib.hex, fib.lst, fib.sym next to it
cook fib.aura -o build/fib.hex           # choose the output name
cook fib.aura --format plain             # one 4-digit hex word per line instead of v2.0 raw
cook fib.aura --boring                   # plain error messages, no roasts
cook fib.aura -W error                   # treat warnings as errors
uncook fib.hex [--sym fib.sym] [--boring]   # disassemble
```

(`cook` is `python tools/cook.py`. Alias it.)

### 11.2 Source format

- One statement per line: `[label:] [mnemonic operands] [; comment]`
- **Labels:** `[A-Za-z_][A-Za-z0-9_]*`, case-sensitive. A label can't reuse a mnemonic, alias, register name, directive or predefined symbol.
- **Mnemonics, registers (`R0`–`R7`) and directives** are case-insensitive. House style is SHOUTING the mnemonics, because slang should be shouted.
- **Operands** are separated by commas. There are four kinds: a register `R3` (or a `.def` name), a pointer `[R3]`, an expression, and a string `"..."` (YAP only).
- **Comments** start with `;` when it's outside quotes.

### 11.3 Numbers and expressions

- **Literals:** `42`, `-5`, `0x2A`, `0b101010`, `'A'`, `'\n'`. Escapes: `\n \t \r \0 \\ \' \" \xHH`.
- **Symbols:** labels, `.equ` constants and predefined names (§11.6). `.` is the address of the current instruction.
- **Operators**, using C precedence, highest first: unary `-` and `~`, then `* / %`, then `+ -`, then `<< >>`, then `&`, then `^`, then `|`. Parentheses work as expected.
- **Functions:** `lo(x)` = x AND `0xFF`; `hi(x)` = (x >> 8) AND `0xFF`. They're for 16-bit constants: `MANIFEST R0, lo(1000)` then `MANIFEST R1, hi(1000)`.
- Expressions are evaluated as unbounded integers and range-checked at the end: K must be −128..255, and addresses must be 0..255.

### 11.4 Directives

| Directive | Meaning |
|---|---|
| `.org expr` | Set the address of the next instruction |
| `.equ NAME = expr` | Define a constant. It must be defined before it's used. |
| `.def NAME = Rn` | Register alias, e.g. `.def score = R4` (AVR syntax) |
| `.word expr, …` | Raw 16-bit words, for tests and cursed experiments |
| `.include "file.aura"` | Paste another file in here; the path is relative to the current file |

### 11.5 Operand patterns and boring aliases

Overloaded slang mnemonics choose their encoding from the operand kinds:

| Mnemonic | Operands → opcode |
|---|---|
| AURA, AURAFARM, TAX, BACKTAX, MUTUALS, COLLAB, BEEF | (reg, reg) → `01xxx`; (reg, expr) → `11xxx` |
| VIBECHECK | (reg, reg) → `00010`; (reg, expr) → `10010` |
| SUS | (reg, reg) → `00100`; (reg, expr) → `10100`; (reg) → `SUS Rd, Rd` |
| LURK | (reg, [reg]) → `00110`; (reg, expr) → `10101` |
| POST | ([reg], reg) → `00111`; (expr, reg) → `10110` |

Everything else has exactly one form. Any other combination is an error that names the forms that would have worked.

**Boring aliases** follow AVR's names and AVR's split between register and immediate forms. Where AVR has no name, the alias is marked †.

| Boring | Slang | Boring | Slang | Boring | Slang |
|---|---|---|---|---|---|
| NOP | CHILL | LDI | MANIFEST | BREQ | FR |
| HALT | TOUCHGRASS | MOV | LARP | BRNE | CAP |
| SEI | DOOMSCROLL | LDS / LD | LURK | BRLO, BRCS | FUMBLED |
| CLI | LOCKIN | STS / ST | POST | BRSH, BRCC | SECURED |
| RET | ITSOVER | ADD / ADDI † | AURA | BRMI | COOKED |
| RETI | WEREBACK | ADC / ADCI † | AURAFARM | BRPL | LETHIMCOOK |
| BREAK | BRUH | SUB / SUBI | TAX | BRLT | MOGGED |
| PUSH | STASH | SBC / SBCI | BACKTAX | BRGE | MOGGING |
| POP | GRAB | AND / ANDI | MUTUALS | INC / DEC | GLOWUP / FELLOFF |
| JMP | BET | OR / ORI | COLLAB | COM / NEG | CRASHOUT / UNOREVERSE |
| CALL | HITUP | EOR / EORI † | BEEF | LSR / ASR / ROR | LOWKEY / MID / SPIN |
| CP / CPI | VIBECHECK | TST / TSTI † | SUS | SWAP | TRADE |
| CPC | DOUBLECHECK | CLR / SER | GHOST / MAXX | LSL / ROL | HIGHKEY / NIPS |

The boring load and store forms are written `LD Rd, [Rb]` and `ST [Rb], Ra`. AURA-8 has no X, Y or Z pointer registers.

`uncook --boring` and `twin --boring` print boring names. They're useful for comparing against AVR code from lectures.

### 11.6 Predefined symbols

| Symbols | Values |
|---|---|
| I/O registers | `VIBES SP LEDS BUTTONS HEX TTY KBD DELULU TCTRL TTOP TCNT MROW MDATA IMASK IFLAGS CHAT` (`0xF0`–`0xFF`, §9.1) |
| Memory | `RAMEND` = `0xEF` |
| Vectors | `VEC_RESET` = 0, `VEC_TIMER` = 1, `VEC_BUTTON` = 2, `VEC_KEY` = 3 |
| Interrupt bits | `IRQ_TIMER` = 1, `IRQ_BUTTON` = 2, `IRQ_KEY` = 4 |
| Timer settings | `TIMER_DIV1` = `0x01`, `TIMER_DIV8` = `0x03`, `TIMER_DIV64` = `0x05`, `TIMER_DIV256` = `0x07` |

### 11.7 How it works: two passes

1. **Pass 1:** read the lines (expanding `.include`), evaluate `.equ` and `.def`, and assign every label its address. Every instruction is 1 word except `YAP` (2n + 2) and `.word` (one per value), so sizes are known without encoding anything.
2. **Pass 2:** encode each instruction now that every label is known, range-check the operands and detect overlapping `.org` regions.
3. **Checks:** the program fits in 256 words, then warnings (§11.8).

Why two passes? Forward references: `FUMBLED done` appears before `done:` is defined, so its offset can't be computed on the first read. This is a classic exam question.

### 11.8 Errors and warnings

Every message gives the file, line and column, the source line with the bad part underlined, and a plain explanation. Unless you pass `--boring`, it adds a roast:

```
fib.aura:9:17: error: undefined symbol 'dne'
    9 |         FUMBLED dne
      |                 ^^^
      = did you mean 'done'? it's giving typo.
```

| Problem | Boring message | Roast |
|---|---|---|
| Unknown mnemonic | `unknown mnemonic 'STAHS'` | did you mean STASH? typing is hard, chief |
| Wrong operand kinds | `AURA takes (reg, reg) or (reg, K); got (K, reg)` | be so fr |
| Immediate out of range | `300 doesn't fit in 8 bits (-128..255)` | that's too much aura for one byte |
| Address out of range | `address 0x1A0 is outside 0x00..0xFF` | that address is delulu |
| Undefined symbol | `undefined symbol 'dne'` | it's giving typo |
| Duplicate label | `'loop' already defined on line 7` | no clones |
| Overlap | `two things at 0x04 (lines 3 and 9)` | this spot is taken |
| Program too big | `needs 271 words; ROM holds 256` | you're cooked (hint: YAP costs 2 words per character) |
| Bad register | `there is no R9` | there are 8 registers. count them. |

Warnings:
- The program uses `DOOMSCROLL` but a vector is still `CHILL`. An interrupt there would slide into the next vector, so put `WEREBACK` in unused vectors.
- A label is defined but never used.
- A `.word` decodes as an INT word. Executing it from ROM re-enters the handler forever, which is cursed.
- `YAP` inside an interrupt handler: it works, but it's 2n + 2 cycles with interrupts off.

### 11.9 Output files

**`.hex`** uses Logisim's `v2.0 raw` format: the first line is `v2.0 raw`, then 256 words as 4-digit hex, 8 per line. Logisim-evolution loads it straight into a ROM component. Digital can import ROM contents from a file too. If your version doesn't accept this format, use `--format plain` (one word per line). Here's the start of `hello.hex`:

```
v2.0 raw
8004 0005 0005 0005 0f00 ff61 b7f5 ff75
b7f5 ff72 b7f5 ff61 b7f5 ff20 b7f5 ff2b
b7f5 ff31 b7f5 ff0a b7f5 2f00 0001 0000
...
```

**`.lst`** lists each address, the word(s) there and the source line. Expanded pseudo-instructions show every word they produced (see §14.2).

**`.sym`** has one `name value` per line. `twin` and `uncook` use it to show labels instead of raw addresses.

**`uncook`** decodes every word. All 65,536 words decode to something, because all 32 opcodes are defined. Words with non-zero "must be 0" bits get a `; nonstandard` comment, and INT words are shown as `; INT (hardware only)`.

---

## 12. Emulator: `twin`

*The circuit's digital twin.* `twin` is the **golden model**: when the circuit and `twin` disagree, `twin` is right, unless you've found a bug in the spec. In that case, fix the spec first.

### 12.1 Usage

```
twin programs/fib.hex                        # run until TOUCHGRASS; TTY to stdout, CHAT as "chat:" lines
twin programs/tick.hex --cycles 4000 --key 1000:hi
twin programs/dodge.hex --button 500:0x01 --button 520:0x00
twin programs/fib.hex --trace | head -20     # one line per cycle
twin programs/math.hex --debug               # interactive debugger
twin programs/dodge.hex --panel              # live LEDs / HEX / LED matrix in the terminal
twin programs/fib.hex --boring               # boring mnemonics in traces
twin programs/fib.hex --cosmic-rays 1e-4 --seed 7
```

The `.sym` file next to the `.hex` is loaded automatically.

### 12.2 Cycle model (must match the hardware)

```
each cycle:
  1. inputs:  --key text scheduled for this cycle joins the KBD buffer;
              --button value scheduled for this cycle replaces BUTTONS
  2. decide:  take = I and (IFLAGS & IMASK) != 0 and not shadow     (start-of-cycle values)
  3. execute: the instruction at PC, or the INT word if take
              (registers, RAM, I/O writes, SP, VIBES, PC)
  4. edge:    peripherals update from START-of-cycle values:
                button rising edge          -> IFLAGS.BUTTON
                timer tick / compare        -> TCNT, IFLAGS.TIMER   (a CPU write to TCNT wins)
                prescaler + 1
                IFLAGS write-1-to-clear and INT ack (a new event beats a clear)
                KBD pops if it was read; DELULU steps if it was read (and not written)
  5. shadow <- set by this instruction?;   cycle <- cycle + 1
```

Implementation hint: take a snapshot of the timer state before step 3 and commit afterwards. That's exactly what flip-flops do.

**Stopping:**
- `TOUCHGRASS` with I = 0, or with IMASK = 0 → exit with "touched grass after N cycles".
- `TOUCHGRASS` with interrupts possible → keep running. Exit early with "asleep forever" if the timer is off and no scripted input is left.
- Otherwise stop at `--cycles` (default 1,000,000).

### 12.3 Devices in the terminal

- TTY → stdout.
- CHAT → `chat: 0x2A (42)` lines on stderr.
- `--panel` redraws a panel whenever a device changes: LEDs as `●○○●…`, HEX, the 8×8 matrix as `██`/`··`, timer state and flags.

### 12.4 Debugger (`--debug`)

| Command | What it does |
|---|---|
| `s [n]` | Step n instructions (default 1) |
| `c` | Continue until a breakpoint, `BRUH` or halt |
| `b <label or addr>` | Toggle a breakpoint |
| `r` | Registers, flags, SP and PC |
| `m <addr> [n]` | Dump n bytes of data memory |
| `st` | Show the stack with return addresses labelled |
| `io` | Device state |
| `t` | Toggle tracing |
| `q` | Quit |

### 12.5 Trace format

One line per cycle, showing what changed (this is from `fib.aura`):

```
cycle   pc  word  instruction            changes
000003  06  B0FF  POST CHAT, R0          CHAT <- 0x00
000004  07  7A00  LARP R2, R0       R2=0x00
000005  08  4220  AURA R2, R1            R2=0x01  Z=0 N=0 V=0 C=0
000006  09  9A03  FUMBLED done           not taken
```

Interrupt entries show up as `INT TIMER -> 0x01`.

### 12.6 Exit codes

| Code | Meaning |
|---|---|
| 0 | Touched grass (halted normally) |
| 1 | Hit the cycle limit |
| 2 | Stack overflow: a push wrote into I/O space (SP wrapped). "You got cooked." |
| 3 | Bad input file |

### 12.7 Cosmic-ray mode

`--cosmic-rays P --seed S`: in every cycle, with probability P, flip one random bit in a random register or RAM byte, and log where it landed. Use it to see how fragile a program is, and how often a single bit flip changes the output. Radiation-hardened space hardware gets tested this way.

---

## 13. Testing: `frfr`

*For real, for real.*

### 13.1 Layers

| Layer | What's tested | How |
|---|---|---|
| ALU | The `alu` subcircuit on its own | `gen_alu_vectors.py` takes expected values from `twin`'s ALU and writes them as test vectors for your simulator (Logisim-evolution's test-vector feature, or Digital's test-case component). Exhaustive for the 8 unary ops (8 × 256 inputs × 2 carry-in values); at least 5,000 random cases plus every pair from {`0x00`, `0x01`, `0x7F`, `0x80`, `0xFF`} for the binary ops. |
| Decoder | The control ROM image | It's generated from `isa.py`. The test regenerates it and diffs against the file in the circuit. |
| Instructions | Each instruction | `tests/isa/<mnemonic>.aura`: tiny programs with `frfr` expectations, run in `twin`, then the same `.hex` on the circuit. |
| Programs | Whole programs | The §14 examples and the capstone game, with expectations. |
| Differential | Circuit versus `twin` | Same `.hex`, compare CHAT/TTY output and the final registers (§13.3). |

### 13.2 Test file format

Tests are ordinary `.aura` files with `; frfr:` comment lines:

```asm
; frfr: cycles 4000                 maximum cycles (default 100000)
; frfr: key 1000 "hi"               type "hi" at cycle 1000
; frfr: button 500 0x01             set BUTTONS = 0x01 at cycle 500
; frfr: expect R0 == 0x2A
; frfr: expect mem[0x10] == 7
; frfr: expect hex == 4             also: leds == ..., vibes == ...
; frfr: expect chat == [0, 1, 1, 2] every byte written to CHAT, in order
; frfr: expect tty == "aura +1\n"
; frfr: expect cycles == 20
; frfr: expect halted
```

`frfr tests/` runs every file and prints `PASS frfr` or `FAIL (cap detected)` with the expected and actual values.

### 13.3 Differential testing

Run the same `.hex` in `twin` and on the circuit, then compare everything observable: CHAT, TTY, HEX and the final registers. Because the design is single-cycle and the cycle model is exact (§12.2), you can also compare **traces** cycle by cycle when hunting a bug. Add hex-display probes for PC and instr to the circuit, step the clock, and line them up with `twin --trace`. Both Logisim-evolution and Digital have command-line modes that can run a circuit without the GUI. Check your version's docs if you want to automate this.

### 13.4 Coverage checklist

- [ ] Every opcode and every sub-op executed at least once
- [ ] Every branch both taken and not taken
- [ ] Every flag set to 0 and to 1 by every operation that writes it
- [ ] Add/subtract corner cases: `0x7F + 1`, `0x80 − 1`, `0x80 − 0x01`, `0x00 − 0x01`, `0xFF + 0x01`
- [ ] Sticky Z: the `0x1300` versus `0x12FF` case (§6.3)
- [ ] GLOWUP and FELLOFF leave C alone; CRASHOUT sets C; UNOREVERSE of `0x00` and of `0x80`
- [ ] Nested HITUP at least 3 deep, plus a recursive function
- [ ] Every I/O register read and written; the KBD and DELULU read side effects
- [ ] Each interrupt source; two sources pending at once (priority); an interrupt during `TOUCHGRASS`
- [ ] The shadow: a KEY handler that never reads KBD, where main must still make progress
- [ ] A handler that forgets to save VIBES, giving a reproducible wrong branch. Keep it as a "known bad" demo.
- [ ] SP wrapping into I/O is caught by `twin`
- [ ] The timer at every prescaler setting; TCNT written while the timer runs

---

## 14. Example programs

All four programs below are complete. They were assembled and run on a prototype of `cook` + `twin`, and every `frfr` expectation in them passes.

### 14.1 `hello.aura`

```asm
; file: hello.aura  (the classic, but slang)
; frfr: expect tty == "aura +1\n"
; frfr: expect cycles == 20
; frfr: expect halted
.org 0x00
        BET main        ; 0x00 reset vector
        WEREBACK            ; 0x01 TIMER  (unused)
        WEREBACK            ; 0x02 BUTTON (unused)
        WEREBACK            ; 0x03 KEY    (unused)
main:   YAP "aura +1\n"     ; 18 words: STASH R7, 8 x (MANIFEST + POST), GRAB R7
        TOUCHGRASS
```

23 words, 20 cycles. The vector table pattern is the same in every program: reset jumps to `main`, and unused vectors hold `WEREBACK`.

### 14.2 `fib.aura` (and how it encodes)

```asm
; file: fib.aura  (every Fibonacci number that fits in a byte, sent to CHAT)
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
        LARP R2, R0
        AURA      R2, R1      ; c = a + b   (C = 1 if it didn't fit in 8 bits)
        FUMBLED   done        ; it carried out, so c > 255: stop
        LARP R0, R1      ; a = b
        LARP R1, R2      ; b = c
        BET   loop
done:   POST      CHAT, R1    ; the last one that fit
        TOUCHGRASS
```

The listing `cook` produces (comments trimmed):

```
addr word   source
00   8004           BET main
01   0005           WEREBACK
02   0005           WEREBACK
03   0005           WEREBACK
04   F800   main:   MANIFEST  R0, 0
05   F901           MANIFEST  R1, 1
06   B0FF   loop:   POST      CHAT, R0
07   7A00           LARP R2, R0
08   4220           AURA      R2, R1
09   9A03           FUMBLED   done
0A   7820           LARP R0, R1
0B   7940           LARP R1, R2
0C   8006           BET   loop
0D   B1FF   done:   POST      CHAT, R1
0E   0001           TOUCHGRASS
```

Hand-encoding five of them, which is exactly what an exam asks you to do:

| Instruction | Opcode | A | Payload | Binary | Hex |
|---|---|---|---|---|---|
| `MANIFEST R1, 1` | `11111` | `001` (R1) | `00000001` | `1111 1001 0000 0001` | `F901` |
| `AURA R2, R1` | `01000` | `010` (R2) | `001` (R1) + `00000` | `0100 0010 0010 0000` | `4220` |
| `FUMBLED done` (at `0x09`; `done` = `0x0D`) | `10011` | `010` (C = 1) | `0x0D − 0x0A = 3` → `00000011` | `1001 1010 0000 0011` | `9A03` |
| `POST CHAT, R0` | `10110` | `000` (R0) | `0xFF` (CHAT) | `1011 0000 1111 1111` | `B0FF` |
| `BET loop` | `10000` | `000` | `0x06` | `1000 0000 0000 0110` | `8006` |

### 14.3 `math.aura` (subroutines, recursion, the Rizz ABI)

```asm
; file: math.aura  (mul8 and a recursive fact)
; frfr: expect chat == [0x60, 0x18, 120]
; frfr: expect halted
.org 0x00
        BET main
        WEREBACK
        WEREBACK
        WEREBACK
main:   MANIFEST R0, 200
        MANIFEST R1, 123
        HITUP    mul8         ; R1:R0 = 200 * 123 = 24600 = 0x6018
        POST     CHAT, R1     ; 0x60
        POST     CHAT, R0     ; 0x18
        MANIFEST R0, 5
        HITUP    fact         ; R0 = 5! = 120
        POST     CHAT, R0
        TOUCHGRASS

; mul8: unsigned 8 x 8 -> 16-bit multiply (shift-and-add)
;   in:  R0 = a, R1 = b       out: R1:R0 = a * b (R1 = high byte)
;   clobbers R2, R3 (caller-saved); preserves R4 (callee-saved)
mul8:   STASH      R4
        LARP R2, R0      ; R2 = a
        LARP R3, R1      ; R3 = b
        GHOST     R0          ; product = 0
        GHOST     R1
        MANIFEST  R4, 8       ; 8 bits to go
m_loop: HIGHKEY      R0          ; product <<= 1 ...
        NIPS     R1          ; ... carrying into the high byte
        HIGHKEY      R3          ; next bit of b -> C
        SECURED   m_skip      ; C = 0: nothing to add
        AURA      R0, R2      ; product += a
        AURAFARM  R1, 0       ; carry into the high byte
m_skip: FELLOFF   R4          ; FELLOFF leaves C alone and sets Z
        CAP       m_loop
        GRAB     R4
        ITSOVER

; fact: recursive factorial, 8-bit result (n <= 5)
;   in: R0 = n     out: R0 = n!     clobbers R1-R3
fact:   VIBECHECK R0, 2
        FUMBLED   f_base      ; n < 2 (unsigned): answer is 1
        STASH      R0          ; save n
        FELLOFF   R0
        HITUP     fact        ; R0 = (n-1)!
        GRAB     R1          ; R1 = n
        HITUP     mul8        ; R1:R0 = (n-1)! * n
        ITSOVER               ; low byte is in R0
f_base: MANIFEST  R0, 1
        ITSOVER
```

39 words, 350 cycles. At its deepest point (`fact` → `fact` → … → `mul8`) the stack goes down to SP = `0xE6`, using 9 bytes. `AURAFARM R1, 0` (ADCI) is the reason ADCI exists, even though AVR doesn't have it.

### 14.4 `tick.aura` (timer interrupts while main echoes the keyboard)

```asm
; file: tick.aura  (timer counts on HEX while main echoes keys to the terminal)
; frfr: cycles 4000
; frfr: key 1000 "hi"
; frfr: expect tty == "hi"
; frfr: expect hex == 4
; frfr: expect mem[0x00] == 4
.equ TICKS = 0x00             ; RAM byte for the tick count
.org 0x00
        BET main          ; reset
        BET on_timer      ; TIMER
        WEREBACK              ; BUTTON (unused)
        WEREBACK              ; KEY    (unused: main polls KBD)
main:   GHOST    R0
        POST     TICKS, R0    ; RAM isn't guaranteed to start at 0
        MANIFEST R0, 99
        POST     TTOP, R0     ; compare match every 100 timer ticks
        MANIFEST R0, 0b011    ; enable, prescaler /8 -> one interrupt per 800 cycles
        POST     TCTRL, R0
        MANIFEST R0, 0b001    ; IMASK: TIMER only
        POST     IMASK, R0
        DOOMSCROLL            ; interrupts on
echo:   LURK     R1, KBD      ; 0 means no key
        SUS      R1           ; Z = 1 if R1 == 0
        FR       echo         ; <- an interrupt can land between SUS and FR!
        POST     TTY, R1
        BET  echo

on_timer:
        STASH     R0
        LURK     R0, VIBES    ; save the flags (see the arrow above)
        STASH     R0
        LURK     R0, TICKS
        GLOWUP   R0
        POST     TICKS, R0
        POST     HEX, R0
        GRAB    R0
        POST     VIBES, R0    ; restore the flags
        GRAB    R0
        WEREBACK
```

Period = 8 × (99 + 1) = 800 cycles, so in 4,000 cycles the handler runs 4 times. The INTs happen at cycles 800, 1600, 2400 and 3200. Delete the two VIBES lines from the handler and the echo loop will, very occasionally, print garbage: that's the bug from §8.5, live.

---

## 15. Milestones

Build the software first, so you always have a known-good answer to test against. Then build the hardware in slices, where each slice runs real programs.

| # | Build | Instructions working | Demo | Done when |
|---|---|---|---|---|
| M0 | Golden model: `isa.py`, `cook`, `twin`, `frfr` | All of them, in software | `twin hello.hex` says aura +1 | The four §14 programs pass in `frfr` |
| M1 | ALU | (none) | ALU test vectors | Every generated vector passes |
| M2 | PC, ROM, register file, decoder, ALU writeback | CHILL, TOUCHGRASS, MANIFEST, LARP, all register and immediate ALU forms, BET | A counter on a probe | Matches `twin --trace` for the first 100 cycles |
| M3 | VIBES and branches | + VIBECHECK, DOUBLECHECK, SUS, all 8 branches, the unary group | Fibonacci in registers | Every branch test passes, taken and not taken |
| M4 | Data memory and basic I/O | + LURK and POST (both forms); LEDS, BUTTONS, HEX, TTY, CHAT | `hello.aura` on the terminal | `hello.aura` and `fib.aura` pass on the circuit |
| M5 | Stack | + STASH, GRAB, HITUP, ITSOVER; SP memory-mapped | Recursive factorial | `math.aura` shows `0x60 0x18 0x78` on CHAT |
| M6 | Interrupts and the rest of I/O | + DOOMSCROLL, LOCKIN, WEREBACK, BRUH, INT; timer, button edges, KBD, DELULU, IMASK, IFLAGS, the shadow | `tick.aura` | `tick.aura` passes; the shadow test passes; the forgot-to-save-VIBES demo fails exactly as predicted |
| M7 | LED matrix and the capstone game | Everything | Tax Dodge | Playable on the circuit; its `frfr` test passes |
| M8 | Ship it | (none) | README with a GIF | Someone else can clone it, run `frfr`, and play the game |

### 15.1 Capstone: Tax Dodge (`programs/dodge.aura`)

Taxes fall from the sky. Don't get taxed.

- **Board:** the 8×8 LED matrix. The player is one lit pixel on row 7 (the bottom).
- **Taxes:** pixels that appear on row 0 in a random column (`DELULU AND 7`) and fall one row per game tick.
- **Game tick:** the TIMER interrupt.
- **Controls:** `a` and `d` move left and right, through the KEY interrupt. Alternatively use buttons 0 and 1 through the BUTTON interrupt.
- **Score:** +1 for every tax that reaches the bottom row without hitting you, shown on HEX. Every 8 points, lower TTOP so the game speeds up.
- **Game over:** a tax lands in your column. Then `LOCKIN`, `YAP "TAXED\n"`, leave the final score on HEX and `TOUCHGRASS`.
- **Constraints:** it must fit in 256 words, YAPs included (`"TAXED\n"` alone costs 14). Keep the board as 8 bytes of RAM, one per row. To make things fall, copy row i−1 into row i from the bottom up, then redraw with MROW and MDATA.
- **Test:** a `frfr` script that dodges for a while with scripted `key` lines, then expects `tty == "TAXED\n"` and a known score. DELULU is deterministic, so the same keys always give the same game.

---

## 16. Stretch goals (aura farming)

1. **Microcoded rebuild.** Make it multi-cycle, with explicit FETCH → DECODE → EXECUTE states driven by a microcode ROM, then compare cycles per instruction with the single-cycle version. This is the best state-machine exercise in the whole project.
2. **Two-stage pipeline** (fetch | execute), flushing on taken branches.
3. **`READTHEROOM Rd, [Rb]`** (AVR's LPM): read the low byte of a ROM word as data, for lookup tables and strings without `YAP`. Encode it as `LURK Rd, [Rb]` with payload bit 0 set; those bits are currently must-be-zero. It needs a second read port on the ROM, or a second copy of the ROM.
4. **`MOG Rd, Rb`**: hardware multiply into R1:R0, like AVR's MUL. Use a spare low payload bit of an R-format instruction (the same trick MIPS plays with its function field). An array multiplier is a lot of adders.
5. **Bigger programs:** a PAGE register for bank switching past 256 words. Calls then have to save the page too.
6. **FPGA:** both simulators can export a circuit as a hardware description for FPGA boards. Check which boards your version supports.
7. **A slang high-level language** that compiles to `.aura`: `bet x = 5`, `fr x == 5 { ... }`.
8. **Cosmic rays in hardware:** a bit-flip injector subcircuit driven by its own LFSR.
9. **Real-world I/O:** LED-matrix row multiplexing and button debouncing.
10. **`twin` in C:** good embedded-C practice (bit masks, structs, a big `switch`), and then you have two golden models that have to agree.

---

## 17. CSSE2010 map and exam drills

### 17.1 Where each topic shows up

| CSSE2010 topic | Where it lives in AURA-8 | Section |
|---|---|---|
| Binary, hex, two's complement | Immediates, branch offsets, the N, V and C flags, signed versus unsigned branches | §5, §6 |
| Boolean algebra and logic gates | ALU logic unit, branch condition, hand-made decoder logic | §10.6, §10.7 |
| Combinational circuits: mux, decoder, adder, comparator, encoder | Register file, ALU, address decoder, priority encoder | §10 |
| Sequential circuits: flip-flops, registers, counters, state machines | PC, SP, timer and prescaler, LFSR, button edge detector, shadow bit; the microcoded stretch goal | §9, §10, §16 |
| Memory organisation and address decoding | RAM versus I/O split at `0xF0` | §3.3, §9 |
| Instruction sets and encoding | Formats and the opcode map | §4 |
| Assembly language and flow of control | The example programs | §14 |
| The CPU stack and subroutines | STASH, GRAB, HITUP, ITSOVER, the Rizz ABI | §7 |
| Interrupts and interrupt service routines | Vectors, priority, saving VIBES, the shadow | §8 |
| Interfacing and communication | Memory-mapped devices, timer, keyboard, side-effect reads | §9 |
| Assembling and linking | `cook`'s two passes and symbol table | §11 |
| Embedded C | Write `twin` in C | §16, §20 |

### 17.2 Drills

Answers are folded underneath each one. Try them first.

**1. Encode `TAX R3, 7` and `MANIFEST R0, -5` in hex.**
<details><summary>Answer</summary>

`TAX R3, 7` = `11010 011 00000111` = `0xD307`. `MANIFEST R0, -5`: −5 is `0xFB` in two's complement, so it's `11111 000 11111011` = `0xF8FB`.
</details>

**2. A `FR` at address `0x10` jumps back to `0x0A`. What's the offset, and the instruction word?**
<details><summary>Answer</summary>

o = `0x0A` − (`0x10` + 1) = −7 = `0xF9`. The word is `10011 000 11111001` = `0x98F9`.
</details>

**3. R0 = `0x80`, R1 = `0x01`, then `VIBECHECK R0, R1`. What are Z, N, V and C, and which of the 8 branches are taken?**
<details><summary>Answer</summary>

`0x80 − 0x01 = 0x7F`. Z = 0, N = 0, V = 1 (−128 − 1 overflows), C = 0 (no borrow: 128 ≥ 1). Taken: `CAP`, `SECURED`, `LETHIMCOOK` and `MOGGED`. Unsigned says 128 ≥ 1, signed says −128 < 1, and both are right.
</details>

**4. The clock is 1 kHz. Choose TCTRL and TTOP for one interrupt every 1.024 s. Then try exactly 0.5 s.**
<details><summary>Answer</summary>

1.024 s is 1024 cycles = 256 × 4, so TCTRL = `0x07` (÷256) and TTOP = 3. For 0.5 s, 500 cycles **can't** be done exactly: ÷1 needs TTOP = 499 (doesn't fit in 8 bits), and ÷8 would need TTOP + 1 = 62.5. The closest are ÷8 with TTOP = 61 or 62 (496 or 504 cycles), or do it exactly with ÷1, TTOP = 249 (250 cycles) and count two interrupts in software.
</details>

**5. SP = `0xEF`. `HITUP f` sits at `0x05`, and `f` starts with `STASH R4` then `STASH R5`. What's in `0xEF`, `0xEE` and `0xED`, and what's SP?**
<details><summary>Answer</summary>

`0xEF` = `0x06` (the return address), `0xEE` = R4, `0xED` = R5, and SP = `0xEC`.
</details>

**6. Write `reg_we` as a minimal sum of products of the opcode bits o4..o0 (= instr[15:11]).**
<details><summary>Answer</summary>

Rows `01` and `11` always write (o3 = 1). The other writers are GRAB `00101`, LURK [Rb] `00110`, LURK k `10101` and the unary group `10111`. With o3 = 1 covered by its own term, a K-map gives:

reg_we = o3 + o2·o0·(o4 + ¬o1) + ¬o4·o2·o1·¬o0
</details>

**7. Why does INT push PC but HITUP pushes PC + 1?**
<details><summary>Answer</summary>

HITUP has *finished* executing when it pushes, so the return address is the next instruction. INT replaces an instruction that never ran, so it has to come back to that same instruction.
</details>

**8. Why must an interrupt handler save VIBES, and why doesn't the hardware just do it?**
<details><summary>Answer</summary>

The handler can land between a flag-setting instruction and the branch that reads the flags (§8.5). The hardware, like AVR, leaves it to software so that handlers that don't touch flags stay short. That's a trade-off, not a law.
</details>

**9. Why does `cook` need two passes?**
<details><summary>Answer</summary>

Forward references. A branch to a label defined further down can't be encoded until that label's address is known.
</details>

**10. Design the BUTTON edge detector for one input bit.**
<details><summary>Answer</summary>

One D flip-flop stores last cycle's value. `rising = now AND NOT last`. For 8 buttons, OR the 8 `rising` signals into the IFLAGS.BUTTON set input.
</details>

---

## 18. Differences from AVR

AURA-8 is AVR-*shaped*, not AVR. Here's where they differ, so you don't walk into the exam with the wrong facts:

| Topic | AVR (ATmega324A) | AURA-8 |
|---|---|---|
| Registers | 32 (R0–R31); LDI, CPI, SUBI, ANDI and friends only work on R16–R31 | 8; every instruction works on every register |
| PC and return address | 14-bit PC; CALL pushes 2 bytes | 8-bit PC; HITUP pushes 1 byte |
| Instruction size | Mostly 16-bit; JMP, CALL, LDS and STS are 32-bit | Always 16-bit |
| I/O access | A separate I/O space (IN, OUT, SBI, CBI, SBIS, SBIC), and also memory-mapped | Memory-mapped only (LURK, POST) |
| Status register | SREG has I T H S V N Z C | VIBES has I V N Z C (no T, H or S) |
| Skip instructions | SBRS, SBRC, SBIS, SBIC, CPSE | None: use SUS and then a branch |
| Immediate forms | SUBI, SBCI, ANDI, ORI, CPI, LDI; no ADDI, ADCI, EORI or TSTI | Every two-operand ALU instruction has an immediate form |
| Branch range | 7-bit offset (−64..+63 words) | 8-bit, reaches all 256 words |
| Interrupt vectors | 2 words each (room for a JMP) | 1 word each |
| Extras | MUL, LPM, ADIW/SBIW, X/Y/Z pointers with post-increment | None (MUL and LPM are stretch goals) |

**The same as AVR**, deliberately, so these are safe to learn from either:
- C means borrow after a subtract.
- Sticky Z on SBC, SBCI and CPC.
- INC and DEC don't touch C; COM sets C.
- A push stores first, then decrements SP.
- Interrupt entry clears I and doesn't save the status register; RETI sets I.
- One instruction always runs after SEI or RETI before the next interrupt.
- The lowest vector has the highest priority.
- CMP is SUB without writeback.

---

## 19. Glossary

| Word | Slang meaning | Instruction | Why it fits |
|---|---|---|---|
| BET | "Okay, deal" | JMP | Bet, we're going there |
| HITUP / ITSOVER / WEREBACK | Contact someone / "it's so over" / "we're so back" | CALL / RET / RETI | The call ends; after an interrupt, interrupts are so back |
| STASH / GRAB | Put away / take back | PUSH / POP | Onto the stack, off the stack |
| LURK / POST | Read without posting / post | LD / ST | Read memory / write memory |
| MANIFEST | Speak it into existence | LDI | The constant just appears |
| LARP | Pretend to be someone you're not | MOV | One register pretends to be another |
| AURA / AURAFARM | Cool points / farming them | ADD / ADC | ADC farms the extra carry |
| TAX / BACKTAX | Something gets taken from you / owing old taxes | SUB / SBC | The borrow is back taxes |
| MUTUALS / COLLAB / BEEF | Follow each other / team up / conflict | AND / OR / XOR | Both / either / where they disagree |
| VIBECHECK / DOUBLECHECK / SUS | Check / check again / suspicious | CP / CPC / TST | Look but don't touch |
| GLOWUP / FELLOFF | Improve / decline | INC / DEC | +1 / −1 |
| CRASHOUT | Lose it completely | COM | Every bit flips |
| UNOREVERSE | The Uno reverse card | NEG | Flip the sign |
| LOWKEY / HIGHKEY | Quietly / openly | LSR / LSL | Shift down / shift up |
| MID | Mediocre | ASR | Halved, but it keeps its sign |
| SPIN / NIPS | Spin / "spin" backwards | ROR / ROL | Rotate right / rotate left |
| TRADE | Swap places | SWAP | The nibbles trade places |
| GHOST / MAXX | Ghosting / maxxing | CLR / SER | All zeros / all ones |
| FR / CAP | For real / lie | BREQ / BRNE | Equal / not equal |
| FUMBLED / SECURED | Lost / secured the bag | BRLO / BRSH | Unsigned less / greater or equal |
| COOKED / LETHIMCOOK | Doomed / keep going | BRMI / BRPL | Negative / not negative |
| MOGGED / MOGGING | Outclassed / outclassing | BRLT / BRGE | Signed less / greater or equal |
| CHILL / TOUCHGRASS / BRUH | Relax / go outside / disbelief | NOP / HALT / BREAK | |
| DOOMSCROLL / LOCKIN | Let the distractions in / focus | SEI / CLI | Interrupts on / off |
| BRAINROT | Mindless scrolling you can't escape | `RJMP PC` | An infinite loop |
| IYKYK | If you know, you know | INT | Only the hardware ever sees it |
| YAP / SIXSEVEN | Talk a lot / the 6-7 meme | print string / load 67 | |
| VIBES / DELULU / CHAT | Vibe / delusional / "chat, is this real?" | SREG / random / debug port | |

---

## 20. Decisions you might want to change

These are defaults, not laws. Changing any of them is cheap if you do it before M2.

1. **Simulator.** Logisim-evolution is what many courses use. Digital simulates faster and has built-in test cases. Nothing in this spec depends on the choice, so if your pracs use one of them, use that one and the skills carry over.
2. **Tool language.** Python is quickest. C gives you embedded-C practice (§16, item 10).
3. **Mnemonics.** Find one too cringe, or not cringe enough? It's one line in `isa.py`.
4. **Single-cycle first.** Recommended, because you get a working CPU fastest. If you'd rather start with the state-machine version, do the microcoded design from §16 instead; the ISA doesn't change.
5. **The I/O map.** If your simulator lacks a component (say, the LED matrix), drop that register and keep the address reserved.

Now go touch grass.