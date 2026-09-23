import sys
from pathlib import Path
from enum import Enum

import my6502.utils as utils

"""
This file creates object files after parsing assembly files.
"""

def valid_label(line_num: int, text: str) -> bool:
    """ Check if the label is valid. """
    if len(text) == 0:
        return False
    if text[0] in "0123456789-+$%" or text[0].isspace():
        return False
    for c in text:
        # Obviously in a different implementation use the character codes
        v = ord(c)
        if ord('A') <= v or v <= ord('Z'):
            continue
        if ord('a') <= v or v <= ord('z'):
            continue
        if ord('0') <= v or v <= ord('9'):
            continue
        if v == '_':
            continue
        return False
    return True

class AddressingBehavior(Enum):
    COMPACT_TO_ZPG_IF_POSSIBLE = 1
    FORCE_ZPG = 2
    FORCE_FULL = 3

class AddressType(Enum):
    U16 = 1
    U8 = 2
    S8 = 3

class LabelExpression:
    def __init__(self, addr_type: AddressType, line_num: int, no_labels: bool = False):
        """ Initialize an expression with either 8 or 16 bits. """
        # Each term consists of:
        # - the sign (True if positive, False if negative)
        # - either:
        #   - a label (string)
        #   - a number
        # The expression can only consist of addition and subtraction;
        # all terms are added together.
        self.addr_type = addr_type
        self.line_num = line_num
        self.no_labels = no_labels
        self.unresolved_labels: list[tuple[str, int]] = []
        self.offset = 0

    
    def write_to_file(self, file) -> None:
        file.write(self.addr_type.value.to_bytes(1))
        utils.write_compressed_int(file, self.line_num)
        file.write(self.no_labels.to_bytes(1))
        
        utils.write_compressed_int(file, len(self.unresolved_labels))
        for lbl, term_sign in self.unresolved_labels:
            utils.write_compressed_int(file, len(lbl))
            file.write(lbl.encode("ascii"))
            file.write(term_sign.to_bytes(1, signed=True))
        
        utils.write_compressed_int(file, self.offset, signed=True)

    @staticmethod
    def from_file(file) -> LabelExpression:
        type_id = int.from_bytes(file.read(1))

        addr_type = None
        match type_id:
            case AddressType.U16.value:
                addr_type = AddressType.U16
            case AddressType.U8.value:
                addr_type = AddressType.U8
            case AddressType.S8.value:
                addr_type = AddressType.S8
            case _:
                raise Exception(f"Error: Invalid label expression type")

        line_num = utils.read_compressed_int(file)

        lblexpr = LabelExpression(addr_type, line_num)
        lblexpr.no_bytes = bool(int.from_bytes(file.read(1)))

        ul_sz = utils.read_compressed_int(file)
        for _ in range(ul_sz):
            lbl_sz = utils.read_compressed_int(file)
            lbl = file.read(lbl_sz).decode("ascii")
            term_sign = int.from_bytes(file.read(1), signed=True)
            lblexpr.unresolved_labels.append((lbl, term_sign))

        lblexpr.offset = utils.read_compressed_int(file, signed=True)

        return lblexpr

    
    def parse(self, text: str) -> None:
        if len(text) == 0:
            raise Exception(f"Error: Ln {self.line_num}: Empty address string")
        tok = ""
        term_sign = 1
        term_sign_set = False

        for c in text:
            if not c.isspace():
                tok += c
                continue
            if len(tok) == 0:
                continue
            term_sign, term_sign_set = self.interpret_tok(tok, term_sign, term_sign_set)
            tok = ""

        if len(tok) > 0:
            self.interpret_tok(tok, term_sign, term_sign_set)

    def interpret_tok(self, tok: str, term_sign: int, term_sign_set: bool) -> tuple[int, bool]:
        # Enforce numeric only for numbers, erroring if Python hexadecimal and binary values are included
        STRICT_6502_LITERALS = True
        # Set sign and truncate
        if tok[0] == '-':
            if term_sign_set:
                raise Exception(f"Error: Ln {self.line_num}: Expected label or literal after sign")
            term_sign = -1
            tok = tok[1:] 
            term_sign_set = True
        elif tok[0] == '+':
            if term_sign_set:
                raise Exception(f"Error: Ln {self.line_num}: Expected label or literal after sign")
            term_sign == 1
            tok = tok[1:]
            term_sign_set = True
        if len(tok) == 0:
            return term_sign, term_sign_set

        if tok[0] == '$': # Hexadecimal
            tok = tok[1:]
            if STRICT_6502_LITERALS and len(tok) >= 2 and (tok[1] == 'x' or tok[1] == 'X'):
                raise Exception(f"Error: Ln {self.line_num}: Invalid literal ${tok}")
            self.offset += term_sign * int(tok, 16)
        elif tok[0] == '%': # Binary
            tok = tok[1:]
            if STRICT_6502_LITERALS and len(tok) >= 2 and (tok[1] == 'b' or tok[1] == 'B'):
                raise Exception(f"Error: Ln {self.line_num}: Invalid literal %{tok}")
            self.offset += term_sign * int(tok, 2)
        elif tok[0].isnumeric(): # Decimal
            self.offset += term_sign * int(tok, 10)
        else: # Label (should not be a macro)
            if not valid_label(self.line_num, tok):
                raise Exception(f"Error: Ln {self.line_num}: Label \"{tok}\" contains invalid characters")
            if self.no_labels:
                raise Exception(f"Error: Ln {self.line_num}: Labels not allowed in expression; found \"{tok}\"")
            self.unresolved_labels.append((tok, term_sign))
        return term_sign, False
        

    def resolve(self, label_addrs: dict[str, int]) -> bytes:
        for lbl, sgn in self.unresolved_labels:
            if lbl not in label_addrs:
                raise Exception(f"Error: Ln {self.line_num}: Unknown label \"{lbl}\"")
            self.offset += sgn * label_addrs[lbl]
        self.convert_offset()
        return self.offset.to_bytes(2 if self.addr_type == AddressType.U16 else 1, byteorder="little", signed=self.addr_type == AddressType.S8)

    def resolve_immediately(self) -> bytes | None:
        if len(self.unresolved_labels) > 0:
            return None # Cannot be resolved right now
        self.convert_offset()
        return self.offset.to_bytes(2 if self.addr_type == AddressType.U16 else 1, byteorder="little", signed=self.addr_type == AddressType.S8)

    def convert_offset(self) -> None:
        match self.addr_type:
            case AddressType.U16:
                self.offset %= 0x10000
            case AddressType.U8:
                self.offset %= 0x100
            case AddressType.S8:
                if self.offset not in range(-128, 128):
                    raise Exception(f"Error: Ln {self.line_num}: Relative value exceeds range [-128, 127]")
            case _:
                raise Exception(f"ASSERT Error: Ln {self.line_num}: LabelExpression type not set correctly")


    def __repr__(self):
        s = "<"
        for i, (lbl, term_sign) in enumerate(self.unresolved_labels):
            if i > 0 and term_sign == 1:
                s += "+"
            elif term_sign == -1:
                s += "-"
            s += lbl
        if self.offset != 0:
            s += "{self.offset:+X}"
        s += ">"
        return s


class ObjectCode:
    VERSION = 0x6502_0001

    def __init__(self):
        self.labels: dict[str, tuple[int, int]] = {} # (<LabelName>, (<obj offset>, <line_num>))
        self.offsets_to_resolve: dict[int, LabelExpression] = {} # (<obj offset>, <LabelExpression>)
        self.code_bytes: list[bytearray] = []
        self.obj_offset: int = 0

    def write_to_file(self, file) -> None:
        file.write(ObjectCode.VERSION.to_bytes(4, byteorder="little"))
        file.write(self.obj_offset.to_bytes(4, byteorder="little"))

        utils.write_compressed_int(file, len(self.labels))
        for lbl, (offset, line_num) in self.labels.items():
            utils.write_compressed_int(file, len(lbl))
            file.write(lbl.encode("ascii"))
            utils.write_compressed_int(file, offset)
            utils.write_compressed_int(file, line_num)

        utils.write_compressed_int(file, len(self.offsets_to_resolve))
        for offset, lblexpr in self.offsets_to_resolve.items():
            utils.write_compressed_int(file, offset)
            lblexpr.write_to_file(file)

        utils.write_compressed_int(file, len(self.code_bytes))
        for ba in self.code_bytes:
            utils.write_compressed_int(file, len(ba))
            file.write(ba)    

    @staticmethod
    def from_file(file, path: Path) -> ObjectCode:
        file_VERSION = int.from_bytes(file.read(4), byteorder="little")
        if file_VERSION != ObjectCode.VERSION:
            print(f"Warning: file {path} has version {file_VERSION} differing from object file version {ObjectCode.VERSION}")
        objcode = ObjectCode()
        objcode.obj_offset = int.from_bytes(file.read(4), byteorder="little")
        
        labels_sz = utils.read_compressed_int(file)
        for _ in range(labels_sz):
            lbl_sz = utils.read_compressed_int(file)
            lbl = file.read(lbl_sz).decode("ascii")
            offset = utils.read_compressed_int(file)
            line_num = utils.read_compressed_int(file)
            objcode.labels[lbl] = (offset, line_num)

        otr_sz = utils.read_compressed_int(file)
        for _ in range(otr_sz):
            offset = utils.read_compressed_int(file)
            lblexpr = LabelExpression.from_file(file)
            objcode.offsets_to_resolve[offset] = lblexpr

        cb_sz = utils.read_compressed_int(file)
        for _ in range(cb_sz):
            ba_sz = utils.read_compressed_int(file)
            ba = bytearray(file.read(ba_sz))
            objcode.code_bytes.append(ba)

        return objcode


def main():
    # TODO other handling including help screen
    if len(sys.argv) < 2:
        raise Exception(f"Error: Must specify file to assemble")
    in_id = sys.argv[1]
    path = Path(in_id)
    objcode = assemble_obj_from_file(path)

    # TODO other arguments

    obj_file_path = Path(f"{in_id}.o")
    sep_idx = in_id.rfind('.')
    if "-o" in sys.argv:
        idx = sys.argv.index("-o")
        if idx == len(sys.argv) - 1:
            raise Exception(f"Error: Must specify object file name after '-o' option")
        out_raw = sys.argv[idx+1]
        if len(out_raw) == 0:
            raise Exception(f"Error: Must specify object file name after '-o' option")
        if out_raw[0] == '-':
            raise Exception(f"Error: flag '-' found at start of object file name argument")
        obj_file_path = Path(out_raw)
    elif sep_idx != -1:
        obj_file_path = Path(f"{in_id[:sep_idx]}.o")
    write_obj_to_file(objcode, obj_file_path)

def assemble_obj_from_file(path: Path) -> ObjectCode:
    if not path.is_file():
        raise Exception(f"Error: File {path.resolve()} does not exist")
    objcode = ObjectCode()
    with path.open() as f:
        for line_num, line in enumerate(f, start=1):
            parse_asm_line(line_num, line, objcode)
    return objcode

def write_obj_to_file(objcode: ObjectCode, path: Path) -> None:
    if path.is_dir():
        raise Exception(f"Error: path {path} is a directory")
    with path.open(mode="wb") as f:
        objcode.write_to_file(f)


def parse_asm_line(line_num: int, line: str, objcode: ObjectCode) -> None:
    # Remove anything past comment colon if present
    comment_idx = line.find(';')
    if comment_idx != -1:
        line = line[:comment_idx]
    line = line.strip()
    # Skip line if no actual contents
    if len(line) == 0:
        return

    label_idx = line.find(':')
    if label_idx == 0:
        raise Exception(f"Error: Ln {line_num}: Label colon ':' exists but label string is empty")

    if label_idx > 0:
        label_num = len(objcode.code_bytes) # The next line is where the label starts
        label_str = line[:label_idx]
        if not valid_label(label_num, label_str):
            raise Exception(f"Error: Ln {line_num}: Label \"{label_str}\" is invalid")
        if label_str in objcode.labels:
            raise Exception(f"Error: Ln {line_num}: Label \"{label_str}\" already located at line {objcode.labels[label_str][1]}")
        objcode.labels[label_str] = (label_num, line_num)
        return

    if line[0] == '.':
        parse_directive(line_num, line, objcode)
    else:
        parse_instruction(line_num, line, objcode)

def parse_directive(line_num: int, line: str, objcode: ObjectCode) -> None:
    # TODO other directives; db, org? etc
    return

def parse_instruction(line_num: int, line: str, objcode: ObjectCode) -> None:
    v = bytearray(b'\x00')
    objcode.code_bytes.append(v)
    opcode = line[0:3].lower()
    
    # Attempt to match opcodes of form 0bXXXRRR01
    form_0bXXXRRR01_idx = -1
    match opcode:
        case "ora":
            form_0bXXXRRR01_idx = 0
        case "and":
            form_0bXXXRRR01_idx = 1
        case "eor":
            form_0bXXXRRR01_idx = 2
        case "adc":
            form_0bXXXRRR01_idx = 3
        case "sta":
            form_0bXXXRRR01_idx = 4
        case "lda":
            form_0bXXXRRR01_idx = 5
        case "cmp":
            form_0bXXXRRR01_idx = 6
        case "sbc":
            form_0bXXXRRR01_idx = 7
    if form_0bXXXRRR01_idx != -1:
        v[0] |= (form_0bXXXRRR01_idx << 5) | 1 # XXX bits
        parse_addressing_0bXXXRRR01(line_num, line[3:].strip(), objcode) 
        return

    # Attempt to match opcodes of form 0bXXXRRR10 (excluding transfers, DEX, and NOP)
    form_0bXXXRRR10_idx = -1
    match opcode:
        case "asl":
            form_0bXXXRRR10_idx = 0
        case "rol":
            form_0bXXXRRR10_idx = 1
        case "lsr":
            form_0bXXXRRR10_idx = 2
        case "ror":
            form_0bXXXRRR10_idx = 3
        case "stx":
            form_0bXXXRRR10_idx = 4
        case "ldx":
            form_0bXXXRRR10_idx = 5
        case "dec":
            form_0bXXXRRR10_idx = 6
        case "inc":
            form_0bXXXRRR10_idx = 7
    if form_0bXXXRRR10_idx != -1:
        v[0] |= (form_0bXXXRRR10_idx << 5) | 2 # XXX bits 
        parse_addressing_0bXXXRRR10(line_num, line[3:].strip(), objcode)    
        return

    # Attempt to match special opcodes of form 0bXXXRRR10 (transfers, DEX, NOP)
    # Note: No separate parsing function since all opcodes below have no arguments
    match opcode:
        case "txa":
            v[0] = 0x8a
            return
        case "txs":
            v[0] = 0x9a
            return
        case "tax":
            v[0] = 0xaa
            return
        case "tsx":
            v[0] = 0xba
            return
        case "dex":
            v[0] = 0xca
            return
        case "nop":
            v[0] = 0xea
            return

    # Attempt to match opcodes of form 0bXXXRRR00
    form_0bXXXRRR00_idx = -1
    match opcode:
        case "bit":
            form_0bXXXRRR00_idx = 1
        case "jmp":
            form_0bXXXRRR00_idx = 2
        case "sty":
            form_0bXXXRRR00_idx = 4
        case "ldy":
            form_0bXXXRRR00_idx = 5
        case "cpy":
            form_0bXXXRRR00_idx = 6
        case "cpx":
            form_0bXXXRRR00_idx = 7
    if form_0bXXXRRR00_idx != -1:
        v[0] |= form_0bXXXRRR00_idx << 5 # XXX bits 
        parse_addressing_0bXXXRRR00(line_num, line[3:].strip(), objcode)
        return

    # Attempt to match opcodes of form 0bXXXXX000 <impl>
    match opcode:
        case "brk":
            v[0] = 0x00
            return
        case "rti":
            v[0] = 0x40
            return
        case "rts":
            v[0] = 0x60
            return
        case "php":
            v[0] = 0x08
            return
        case "clc":
            v[0] = 0x18
            return
        case "plp":
            v[0] = 0x28
            return
        case "sec":
            v[0] = 0x38
            return
        case "pha":
            v[0] = 0x48
            return
        case "cli":
            v[0] = 0x58
            return
        case "pla":
            v[0] = 0x68
            return
        case "sei":
            v[0] = 0x78
            return
        case "dey":
            v[0] = 0x88
            return
        case "tya":
            v[0] = 0x98
            return
        case "tay":
            v[0] = 0xa8
            return
        case "clv":
            v[0] = 0xb8
            return
        case "iny":
            v[0] = 0xc8
            return
        case "cld":
            v[0] = 0xd8
            return
        case "inx":
            v[0] = 0xe8
            return
        case "sed":
            v[0] = 0xf8
            return

    # Attempt to match opcodes of form 0bXXX10000
    form_0bXXX10000_idx = -1
    match opcode:
        case "bpl":
            form_0bXXX10000_idx = 0
        case "bmi":
            form_0bXXX10000_idx = 1
        case "bvc":
            form_0bXXX10000_idx = 2
        case "bvs":
            form_0bXXX10000_idx = 3
        case "bcc":
            form_0bXXX10000_idx = 4
        case "bcs":
            form_0bXXX10000_idx = 5
        case "bne":
            form_0bXXX10000_idx = 6
        case "beq":
            form_0bXXX10000_idx = 7
    if form_0bXXX10000_idx != -1:
        v[0] |= (form_0bXXX10000_idx << 5) | 16
        parse_addressing_0bXXX10000(line_num, line[3:].strip(), objcode)
        return

def parse_16_bit_address(line_num: int, text: str) -> LabelExpression:
    """ Parse a 16-bit address. Returns a LabelExpression which may or may not be resolvable immediately. """
    lblexpr = LabelExpression(True, line_num)
    lblexpr.parse(text)
    return lblexpr

def parse_8_bit_address(line_num: int, text: str) -> LabelExpression:
    """ Parse a 8-bit address. Returns a LabelExpression which may or may not be resolvable immediately. """
    lblexpr = LabelExpression(False, line_num)
    lblexpr.parse(text)
    return lblexpr

def resolve_label_expression(line_num: int, lblexpr: LabelExpression, objcode: ObjectCode,
                             compact_to_zpg: AddressingBehavior = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE) -> None:
    sz = len(objcode.code_bytes)
    if sz == 0:
        raise Exception(f"ASSERT Error: Ln {line_num}: Attempted to resolve label expression in an empty object file")

    resolution = lblexpr.resolve_immediately()
    if resolution is None:
        objcode.offsets_to_resolve[sz-1] = lblexpr
    elif (
            compact_to_zpg == AddressingBehavior.FORCE_ZPG and len(resolution) >= 1 or
            compact_to_zpg == AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE and len(resolution) == 2 and resolution[1] == 0
        ):
        objcode.code_bytes[-1].append(resolution[0])
    else:
        objcode.code_bytes[-1] += resolution

def parse_addressing_0bXXXRRR01(line_num: int, text: str, objcode: ObjectCode) -> None:
    if len(text) == 0:
        raise Exception(f"Error: Ln {line_num}: Opcode requires argument")
    v = objcode.code_bytes[-1]
 
    # TODO looser syntax for indexed addressing
    if text[0] == '(': # Indirect addressing modes
        if len(text) >= 4 and text[-3:].lower() == ",x)": # {X-indexed, indirect}; form OPC (<addr8>,X); RRR = 0b000
            addr_text = text[1:-3].strip()
            if len(addr_text) == 0:
                raise Exception(f"Error: Ln {line_num}: Invalid syntax for X-indexed, indirect operation; must be (<addr>,X)")
            #v[0] |= 0b000_000_00 # Not necessary, kept for consistency
            lblexpr = parse_8_bit_address(line_num, addr_text)
            resolve_label_expression(line_num, lblexpr, objcode)
        elif len(text) >= 4 and text[-3:].lower() == "),y": # {Indirect, Y-indexed}; form OPC (<addr8>),Y; RRR = 0b001
            addr_text = text[1:-3].strip()
            if len(addr_text) == 0:
                raise Exception(f"Error: Ln {line_num}: Invalid syntax for indirect, Y-indexed operation; must be (<addr>),Y")
            v[0] |= 0b000_100_00
            lblexpr = parse_8_bit_address(line_num, addr_text)
            resolve_label_expression(line_num, lblexpr, objcode)
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid indirect addressing syntax")
    elif text[0] == '#': # {Immediate}; form OPC #<imm8>; RRR = 0b010
        imm_text = text[1:].strip()
        if len(imm_text) == 0:
            raise Exception(f"Error: Ln {line_num}: Immediate value not specified")
        v[0] |= 0b000_010_00
        if v[0] == 0x89: # $89 ("STA #") is the one illegal opcode in the 0bXXXRRR01 group
            raise Exception(f"Error: Ln {line_num}: STA #<immediate> (opcode $89) is not supported")
        lblexpr = LabelExpression(AddressType.U8, line_num, no_labels=True)
        lblexpr.parse(imm_text)
        resolve_label_expression(line_num, lblexpr, objcode)
    else: # zero age and absolute addressing modes
        split_idx = text.find(',')
        addr_text = text[:split_idx] if split_idx != -1 else text

        # Adapted from NESASM
        addr_behavior = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE
        if addr_text[0] == ">":
            addr_behavior = AddressingBehavior.FORCE_FULL
            addr_text = addr_text[1:]
        elif addr_text[0] == "<":
            addr_behavior = AddressingBehavior.FORCE_ZPG
            addr_text = addr_text[1:]

        lblexpr = LabelExpression(AddressType.U16, line_num)
        lblexpr.parse(addr_text)
        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=addr_behavior)

        is_zpg = len(v) == 2
        if len(v) == 1 and addr_behavior == AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE: # Unresolved, do not permute opcode
            pass
        elif split_idx != -1: # No indexing; RRR = 0b001 if ZPG, 0b011 otherwise
            v[0] |= 0b000_001_00 if is_zpg else 0b000_011_00
        elif text[split_idx:].lower() == ",x": # X-indexed; RRR = 0b101 if ZPG, 0b111 otherwise
            v[0] |= 0b000_101_00 if is_zpg else 0b000_111_00
        elif text[split_idx:].lower() == ",y": # Y-indexed; NO ZPG OPTION; RRR = 0b110
            if addr_behavior == FORCE_ZPG:
                raise Exception(f"Error: Ln {line_num}: Cannot force zero-page addressing for instruction")
            if is_zpg: # Fix unforced ZPG
                v.append(b"\x00")
            v[0] |= 0b000_110_00
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid zero-page/absolute addressing syntax")


def parse_addressing_0bXXXRRR10(line_num: int, text: str, objcode: ObjectCode) -> None:
    if len(text) == 0:
        raise Exception(f"Error: Ln {line_num}: Opcode requires argument")
    v = objcode.code_bytes[-1]

    # TODO looser syntax for indexed addressing
    if text.lower() == "a": # Accumulator; form OPC A; RRR = 0b010
        mask = v[0] >> 5
        if mask == 0b100 or mask == 0b110 or mask == 0b111: # STX, DEC, INC do not support immediate arguments; LDX does
            raise Exception(f"Error: Ln {line_num}: Instruction does not support accumulator operation 'A'")
        v[0] |= 0b000_010_00
    elif text[0] == '#': # {Immediate}; only supported by LDX # (opcode $A2)
        imm_text = text[1:].strip()
        if len(imm_text) == 0:
            raise Exception(f"Error: Ln {line_num}: Immediate value not specified")
        if (v[0] >> 5) != 5: 
            raise Exception(f"Error: Ln {line_num}: Instruction does not support immediate values")
        v[0] = 0xa2
        lblexpr = LabelExpression(AddressType.U8, line_num, no_labels=True)
        lblexpr.parse(imm_text)
        resolve_label_expression(line_num, lblexpr, objcode)
    else: # Zero page and absolute addressing
        split_idx = text.find(',')
        addr_text = text[:split_idx] if split_idx != -1 else text

        # Adapted from NESASM
        addr_behavior = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE
        if addr_text[0] == ">":
            addr_behavior = AddressingBehavior.FORCE_FULL
            addr_text = addr_text[1:]
        elif addr_text[0] == "<":
            addr_behavior = AddressingBehavior.FORCE_ZPG
            addr_text = addr_text[1:]

        lblexpr = LabelExpression(AddressType.U16, line_num)
        lblexpr.parse(addr_text)
        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=addr_behavior)

        is_zpg = len(v) == 2
        if len(v) == 1 and addr_behavior == AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE: # Unresolved, do not permute opcode
            pass
        elif split_idx != -1: # No indexing; RRR = 0b001 if ZPG, 0b011 otherwise
            v[0] |= 0b000_001_00 if is_zpg else 0b000_011_00
        elif text[split_idx:].lower() == ",x": # X-indexed; RRR = 0b101 if ZPG, 0b111 otherwise
            v[0] |= 0b000_101_00 if is_zpg else 0b000_111_00
            if v[0] == 0x96 or v[0] == 0xb6 or v[0] == 0x9e or v[0] == 0xbe:
                raise Exception(f"Error: Ln {line_num}: Instruction does not support X-indexing")
        elif text[split_idx:].lower() == ",y": # Y-indexed; RRR = 0b101 if ZPG, 0b111 otherwise
            v[0] |= 0b000_101_00 if is_zpg else 0b000_111_00
            if v[0] == 0x9e:
                raise Exception(f"Error: Ln {line_num}: STX <absolute>,Y (opcode $9E) is not supported")
            if v[0] != 0x96 and v[0] != 0xb6 and v[0] != 0xbe:
                raise Exception(f"Error: Ln {line_num}: Instruction does not support Y-indexing")
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid zero-page/absolute addressing syntax")


def parse_addressing_0bXXXRRR00(line_num: int, text: str, objcode: ObjectCode) -> None:
    if len(text) == 0:
        raise Exception(f"Error: Ln {line_num}: Opcode requires argument")
    v = objcode.code_bytes[-1]
    xxx_code = v[0] >> 5

    # TODO looser syntax for indexed addressing
    if text[0] == '(' or text[-1] == ')': # Indirect addressing, only for JMP
        if text[0] != '(' or text[-1] != ')':
            raise Exception(f"Error: Ln {line_num}: Invalid indirect accessing syntax")
        if xxx_code != 2:
            raise Exception(f"Error: Ln {line_num}: Instruction does not support indirect addressing")
        v[0] = 0x6c
        addr_text = text[1:-1].strip()
        if len(addr_text) == 0:
            raise Exception(f"Error: Ln {line_num}: Indirect address value not specified")
        lblexpr = parse_16_bit_address(line_num, addr_text)
        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=FORCE_FULL)
    elif xxx_code == 2: # JMP absolute
        v[0] = 0x4c
        lblexpr = parse_16_bit_address(line_num, text)
        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=FORCE_FULL)
    elif text[0] == '#': # {Immediate}; form OPC #<imm8>; RRR = 0b000
        imm_text = text[1:].strip()
        if xxx_code != 5 and xxx_code != 6 and xxx_code != 7: 
            raise Exception(f"Error: Ln {line_num}: Instruction does not support immediate values")
        if len(imm_text) == 0:
            raise Exception(f"Error: Ln {line_num}: Immediate value not specified")
        #v[0] |= 0b000_000_00 # Not necessary
        lblexpr = LabelExpression(AddressType.U8, line_num, no_labels=True)
        lblexpr.parse(imm_text)
        resolve_label_expression(line_num, lblexpr, objcode)
    else: # zero age and absolute addressing modes
        split_idx = text.find(',')
        addr_text = text[:split_idx] if split_idx != -1 else text

        # Adapted from NESASM
        addr_behavior = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE
        if addr_text[0] == ">":
            addr_behavior = AddressingBehavior.FORCE_FULL
            addr_text = addr_text[1:]
        elif addr_text[0] == "<":
            addr_behavior = AddressingBehavior.FORCE_ZPG
            addr_text = addr_text[1:]

        lblexpr = LabelExpression(AddressType.U16, line_num)
        lblexpr.parse(addr_text)
        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=addr_behavior)

        is_zpg = len(v) == 2
        if len(v) == 1 and addr_behavior == AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE: # Unresolved, do not permute opcode
            pass
        elif split_idx != -1: # No indexing; RRR = 0b001 if ZPG, 0b011 otherwise
            v[0] |= 0b000_001_00 if is_zpg else 0b000_011_00
        elif text[split_idx:].lower() == ",x": # X-indexed; RRR = 0b101 if ZPG, 0b111 otherwise
            v[0] |= 0b000_101_00 if is_zpg else 0b000_111_00
            if (
                    v[0] == 0x34 or v[0] == 0x3c # BIT
                    or v[0] == 0xd4 or v[0] == 0xdc # CPY
                    or v[0] == 0xf4 or v[0] == 0xfc # CPX
                ):
                raise Exception(f"Error: Ln {line_num}: Instruction does not support X-indexing")
            elif v[0] == 0x9c: # "STY abs,Y"
                raise Exception(f"Error: Ln {line_num}: STY <16-bit address>,X (opcode $9C) is not supported")
        elif text[split_idx:].lower() == ",x": # No Y-indexing for any of these opcodes
                raise Exception(f"Error: Ln {line_num}: Instruction does not support Y-indexing")
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid zero-page/absolute addressing syntax")


def parse_addressing_0bXXX10000(line_num: int, text: str, objcode: ObjectCode) -> None:
    if len(text) == 0:
        raise Exception(f"Error: Ln {line_num}: Opcode requires argument")
    lblexpr = LabelExpression(AddressType.S8, line_num)
    lblexpr.parse(text)
    resolve_label_expression(line_num, lblexpr, objcode)

if __name__ == "__main__":
    main()
