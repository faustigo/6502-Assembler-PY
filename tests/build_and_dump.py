from my6502.obj import ObjectCode, assemble_obj_from_file, write_obj_to_file
from my6502.objdump import output_obj

from pathlib import Path

asmpath = Path(r".\in\x_loop.asm")
objcode = assemble_obj_from_file(asmpath)

objpath = Path(r".\out\x_loop.o")
write_obj_to_file(objcode, objpath)

objcode = None
with objpath.open(mode="rb") as f:
    objcode = ObjectCode.from_file(f, objpath)

output_obj(objcode)

dumppath = Path(r".\out\x_loop.o.lst")
if dumppath.is_dir():
    raise Exception(f"ASSERT: dumppath {dumppath} is a directory")
with dumppath.open(mode="w") as f:
    output_obj(objcode, out=f)
