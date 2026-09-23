; An example MOS 6502 assembly program.
; These first two lines should NOT be read.
main:
    LDX #$00            ; x = 0;
loop:                   ; do {
    INX                 ;   ++x;
    CPX #$04            ; } while (x < 4)
    BNE loop            ; <jump>
