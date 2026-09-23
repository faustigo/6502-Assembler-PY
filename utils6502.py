def write_compressed_int(file, v: int, signed: bool = False) -> None:
    """ Naive size-data implementation, compressing an int to a size of 2-5 bytes.
        If unsigned, can compress integers in range [0, 127] to 1 byte. """
    bs = v.to_bytes(byteorder="little", signed=signed)
    sz = len(bs)
    if sz < 1:
        raise Exception(f"ASSERT Error: size of int is less than 1 byte")
    if sz > 4:
        raise Exception(f"Error: Cannot compress integer larger than 4 bytes")
    if not signed and sz == 1:
        file.write((v | 0x80).to_bytes(1, signed=False))
    else:
        file.write(sz.to_bytes(1, signed=False))
        file.write(bs)

def read_compressed_int(file, signed: bool = False) -> int:
    """ Naive size-data implementation. See write_compressed_int for details. """
    sz = int.from_bytes(file.read(1), signed=False)
    if not signed and (sz & 0x80) != 0: # One byte unsigned value in range [0, 127]
        return sz & 0x7F
    if sz not in range(1, 5):
        raise Exception(f"Error: Invalid compressed integer must have size [1, 4]; was {sz}")
    return int.from_bytes(file.read(sz), byteorder="little", signed=signed)

