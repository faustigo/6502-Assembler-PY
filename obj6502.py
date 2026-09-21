import sys
from pathlib import Path

"""
This file creates object files after parsing assembly files.
"""

def valid_label(line_num: int, text: str) -> bool:
    """ Check if the label is valid. """
    if len(text) == 0:
        return False
    if text[0] in "0123456789-+$%" or text[0].isspace()
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

class LabelExpression:
    def __init__(self, is_16_bit: bool, line_num: int, no_labels = False: bool):
        """ Initialize an expression with either 8 or 16 bits. """
        # Each term consists of:
        # - the sign (True if positive, False if negative)
        # - either:
        #   - a label (string)
        #   - a number
        # The expression can only consist of addition and subtraction;
        # all terms are added together.
        self.is_16_bit = is_16_bit
        self.line_num = line_num
        self.no_labels = no_labels
        self.unresolved_labels: list[tuple[str, int]] = []
        self.offset = 0

    def parse(self, text: str) -> None:
        if len(text) == 0:
            raise Exception(f"Error: Ln {self.line_num}: Empty address string")
        tok = ""
        term_sign = 1
        term_sign_set = False
        # Enforce numeric only for numbers, erroring if Python hexadecimal and binary values are included
        STRICT_6502_LITERALS = True
        for c in text:
            if not c.isspace():
                tok += c
                continue
            if len(tok) == 0:
                continue

            # Set sign and truncate
            if tok[0] == '-':
                if term_sign_set:
                    raise Exception(f"Error: Ln {self.line_num}: Expected label or literal after sign")
                term_sign_set = True
                term_sign = -1
                tok = tok[1:] 
            elif tok[0] == '+':
                if term_sign_set:
                    raise Exception(f"Error: Ln {self.line_num}: Expected label or literal after sign")
                term_sign_set = True
                term_sign == 1
                tok = tok[1:]
            if len(tok) == 0:
                continue

            term_sign_set = False
            if tok[0] == '$': # Hexadecimal
                if STRICT_6502_LITERALS and len(tok) >= 2 and (tok[1] == 'x' or tok[1] == 'X'):
                    raise Exception(f"Error: Ln {self.line_num}: Invalid literal {tok}")
                self.offset += term_sign * int(tok, 16)
            elif tok[0] == '%': # Binary
                if STRICT_6502_LITERALS and len(tok) >= 2 and (tok[1] == 'b' or tok[1] == 'R'):
                    raise Exception(f"Error: Ln {self.line_num}: Invalid literal {tok}")
                self.offset += term_sign * int(tok, 2)
            elif tok[0].isnumeric(): # Decimal
                self.offset += term_sign * int(tok, 10)
            else: # Label (should not be a macro)
                if not valid_label(self.line_num, tok):
                    raise Exception(f"Error: Ln {self.line_num}: Label \"{tok}\" contains invalid characters")
                if self.no_labels:
                    raise Exception(f"Error: Ln {self.line_num}: Labels not allowed in expression; found \"{tok}\"")
                self.unresolved_labels.append((tok, term_sign))

    def resolve(self, label_addrs: dict[str, int]) -> bytes:
        for lbl, sgn in self.unresolved_labels:
            if lbl not in label_addrs:
                raise Exception(f"Error: Ln {self.line_num}: Unknown label \"{lbl}\"")
            self.offset += sgn * label_addrs[lbl]
        self.offset %= 0x10000 if self.is_16_bit else 0x100
        return self.offset.to_bytes(2 if self.is_16_bit else 1, byte_order="little", signed=False)

    def resolve_immediately(self) -> bytes | None:
        if len(self.unresolved_labels) > 0:
            return None # Cannot be resolved right now
        self.offset %= 0x10000 if self.is_16_bit else 0x100
        return self.offset.to_bytes(2 if self.is_16_bit else 1, byte_order="little", signed=False)


class ObjectCode:
    def __init__(self):
        # TODO offset?
        self.labels: dict[str, int] = {} # (<obj offset>, <LabelName>)
        self.offsets_to_resolve: dict[int, LabelExpression] = {} # (<obj offset>, <LabelExpression>)
        self.bytes: list[bytearray] = []


def main():
    # TODO other handling including help screen
    if len(sys.argv) < 2:
        raise Exception(f"Error: Must specify file to assemble")
    path = Path(sys.argv[1])
    assemble_obj_from_file(path)

def assemble_obj_from_file(path: Path) -> ObjectCode:
    if not path.is_file():
        raise Exception(f"Error: File {path.resolve()} does not exist")
    objcode = ObjectCode()
    with path.open() as f:
        for line_num, line in enumerate(f):
            parse_asm_line(line_num, line, objcode)


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
        label_str = line[:label_idx]
        if not valid_label(line_num, label_str):
            raise Exception(f"Error: Ln {line_num}: Label \"{label_str}\" is invalid")
        if label_str in objcode.labels:
            raise Exception(f"Error: Ln {line_num}: Label \"{label_str}\" already located at line {LABEL_LOCATIONS[label_str]}")
        objcode.labels[label_str] = line_num
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
    objcode.bytes.append(v)
    opcode = line[0:3].lower()
    PROGRAM_COUNTER += 1
    
    # Attempt to match opcodes of form 0bXXXRRR01
    form_0bXXXRRR01_idx = -1
    match opcode:
        case "ora":
            idx = 0
        case "and":
            idx = 1
        case "eor":
            idx = 2
        case "adc":
            idx = 3
        case "sta":
            idx = 4
        case "lda":
            idx = 5
        case "cmp":
            idx = 6
        case "sbc":
            idx = 7
    if form_0bXXXRRR01_idx != -1:
        v[0] |= (idx << 5) | 1 # XXX bits
        parse_addressing_0bXXXRRR01(line_num, line[3:].strip(), v, objcode)    


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
                             compact_to_zpg = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE: AddressingBehavior) -> None:
    if len(objcode.bytes) == 0:
        raise Exception(f"ASSERT Error: Ln {line_num}: Attempted to resolve label expression in an empty object file")

    resolution = lblexpr.resolve_immediately()
    if resolution is None:
        objcode.offsets_to_resolve[line_num] = lblexpr
    elif (
            compact_to_zpg == AddressingBehavior.FORCE_ZPG and len(resolution) >= 1 or
            compact_to_zpg == AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE and len(resolution) == 2 and resolution[1] == 0
        ):
        objcode.bytes[-1] += resolution[0]
    else:
        objcode.bytes[-1] += resolution

def parse_addressing_0bXXXRRR01(line_num: int, text: str, objcode: ObjectCode) -> None:
    if len(text) == 0:
        raise Exception(f"Error: Ln {line_num}: Opcode requires argument")
    v = objcode.bytes[-1]
 
    # TODO looser syntax for indexed addressing
    if line[0] == '(': # Indirect addressing modes
        if len(line) >= 4 and line[-3:] == ",X)": # {X-indexed, indirect}; form OPC (<addr8>,X); RRR = 0b000
            addr_line = line[1:-3].strip()
            if len(addr_line) == 0:
                raise Exception(f"Error: Ln {line_num}: Invalid syntax for X-indexed, indirect operation; must be (<addr>,X)")-
            #v[0] |= 0b000_000_00 # Not necessary, kept for consistency
            lblexpr = parse_8_bit_address(line_num, addr_line)
            resolve_label_expression(line_num, lblexpr, objcode)
        elif len(line) >= 4 and line[-3:] == "),Y": # {Indirect, Y-indexed}; form OPC (<addr8>),Y; RRR = 0b001
            addr_line = line[1:-3].strip()
            if len(addr_line) == 0:
                raise Exception(f"Error: Ln {line_num}: Invalid syntax for indirect, Y-indexed operation; must be (<addr>),Y")-
            v[0] |= 0b000_100_00
            lblexpr = parse_8_bit_address(line_num, addr_line)
            resolve_label_expression(line_num, lblexpr, objcode)
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid indirect addressing syntax")
    elif line[0] == '#': # {Immediate}; form OPC #<imm8>; RRR = 0b010
        imm_line = line[1:].strip()
        if len(imm_line) == 0:
            raise Exception(f"Error: Ln {line_num}: Immediate value not specified")
        v[0] |= 0b000_010_00
        lblexpr = LabelExpression(is_16_bit=False, line_num, no_labels=True)
        lblexpr.parse(imm_line)
        resolve_label_expression(line_num, lblexpr, objcode)
    else: # zero-page and absolute addressing modes
        split_idx = line.find(',')
        addr_line = line[:split_idx] if split_idx != -1 else line

        # Adapted from NESASM
        addr_behavior = AddressingBehavior.COMPACT_TO_ZPG_IF_POSSIBLE
        if addr_line[0] == ">":
            addr_behavior = AddressingBehavior.FORCE_FULL
            addr_line = addr_line[1:]
        elif addr_line[0] == "<":
            addr_behavior = AddressingBehavior.FORCE_ZPG
            addr_line = addr_line[1:]

        resolve_label_expression(line_num, lblexpr, objcode, compact_to_zpg=addr_behavior)

        is_zpg = len(v) == 2
        if len(v) == 1: # Unresolved, do not permute opcode
            pass
        elif split_idx != -1: # No indexing
            v[0] |= 0b000_001_00 if is_zpg else 0b000_011_00
        elif line[split_idx:] == ",X": # X-indexed
            v[0] |= 0b000_101_00 if is_zpg else 0b000_111_00
        elif line[split_idx:] == ",Y": # Y-indexed; NO ZPG OPTION
            if addr_behavior == FORCE_ZPG:
                raise Exception(f"Error: Ln {line_num}: Cannot force zero-page addressing for instruction")
            if is_zpg: # Fix unforced ZPG
                v += b"\x00"
            v[0] |= 0b000_110_00
        else:
            raise Exception(f"Error: Ln {line_num}: Invalid zero-page/absolute addressing syntax")
    if v[0] == b"\x89": # $89 ("STA #") is the one illegal opcode in the 0bXXXRRR01 group
        raise Exception(f"Error: Ln {line_num}: STA #<immediate> is not supported")


if __name__ == "__main__":
    main()
