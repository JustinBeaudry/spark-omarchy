#!/usr/bin/env python3
"""Read-only PE import/export address lookup; no third-party dependencies.

Usage: python pe_symbols.py DLL RVA [RVA ...]
Addresses are hexadecimal RVAs, not relocated process addresses.
Export matches are nearest preceding exports, not guaranteed function names.
"""
import argparse
import bisect
from pathlib import Path
import struct


class PE:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        d = self.data
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        if d[pe:pe + 4] != b'PE\0\0':
            raise ValueError('Not a PE image')
        count, optional_size = self.u16(pe + 6), self.u16(pe + 20)
        opt = pe + 24
        magic = self.u16(opt)
        if magic != 0x20b:
            raise ValueError('Only PE32+ is supported')
        self.directories = opt + 112
        self.sections = []
        for i in range(count):
            s = opt + optional_size + i * 40
            virtual_size, va, raw_size, raw = struct.unpack_from('<4I', d, s + 8)
            self.sections.append((va, max(virtual_size, raw_size), raw, raw_size))

    def u16(self, off):
        return struct.unpack_from('<H', self.data, off)[0]

    def u32(self, off):
        return struct.unpack_from('<I', self.data, off)[0]

    def offset(self, rva):
        for va, size, raw, raw_size in self.sections:
            if va <= rva < va + size and rva - va < raw_size:
                return raw + rva - va
        raise ValueError(f'RVA {rva:#x} not in file-backed section')

    def string(self, rva):
        off = self.offset(rva)
        return self.data[off:self.data.index(b'\0', off)].decode('ascii', errors='replace')

    def imports(self):
        rva = self.u32(self.directories + 8)
        if not rva:
            return {}
        off = self.offset(rva)
        result = {}
        while any(self.data[off:off + 20]):
            original, _, _, name, first = struct.unpack_from('<5I', self.data, off)
            dll = self.string(name)
            thunk = self.offset(original or first)
            i = 0
            while (value := struct.unpack_from('<Q', self.data, thunk + i * 8)[0]):
                symbol = f'ordinal {value & 0xffff}' if value >> 63 else self.string(value + 2)
                result[first + i * 8] = f'{dll}!{symbol}'
                i += 1
            off += 20
        return result

    def exports(self):
        rva = self.u32(self.directories)
        if not rva:
            return []
        off = self.offset(rva)
        count = self.u32(off + 24)
        funcs, names, ordinals = (self.offset(self.u32(off + x)) for x in (28, 32, 36))
        return sorted((self.u32(funcs + self.u16(ordinals + i * 2) * 4),
                       self.string(self.u32(names + i * 4))) for i in range(count))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image')
    p.add_argument('rvas', nargs='+', type=lambda x: int(x, 16))
    args = p.parse_args()
    pe = PE(args.image)
    imports, exports = pe.imports(), pe.exports()
    for rva in args.rvas:
        print(f'{rva:#x}:')
        if rva in imports:
            print('  IAT:', imports[rva])
        i = bisect.bisect_right(exports, (rva, chr(0x10ffff))) - 1
        if i >= 0:
            addr, name = exports[i]
            print(f'  nearest export: {name}+{rva - addr:#x} (not necessarily this function)')


if __name__ == '__main__':
    main()
