"""Version-guarded local changes to vendor files; nothing is redistributed."""
import hashlib
from pathlib import Path
import struct
import zlib
from .common import Error
from .pe import PE


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def patch_foundation(original, output, expected, patched_expected):
    if Path(original).resolve() == Path(output).resolve():
        raise Error('Refusing to overwrite the original Foundation backup.')
    if digest(original) != expected:
        raise Error('Unsupported Foundation.dll checksum. Refusing to patch a different version.')
    pe = PE(original)
    actual = {v.split('!', 1)[1] for v in pe.imports().values()
              if v.split('!', 1)[0].lower() == 'userenv.dll'}
    if actual != {'GetProfilesDirectoryW', 'GetAllUsersProfileDirectoryW'}:
        raise Error('Unexpected USERENV imports; refusing to patch.')
    descriptor = pe.offset(pe.u32(pe.directories + 8))
    locations = []
    while any(pe.data[descriptor:descriptor + 20]):
        name = pe.u32(descriptor + 12)
        if pe.string(name).lower() == 'userenv.dll':
            locations.append(pe.offset(name))
        descriptor += 20
    if len(locations) != 1:
        raise Error('Expected exactly one USERENV import descriptor.')
    offset = locations[0]
    if pe.data[offset:offset + 12].lower() != b'userenv.dll\0':
        raise Error('Unexpected import-name bytes.')
    data = bytearray(pe.data)
    data[offset:offset + 12] = b'spkenv.dll\0\0'
    if hashlib.sha256(data).hexdigest() != patched_expected:
        raise Error('Patched file checksum differs from the reviewed result.')
    Path(output).write_bytes(data)


def extract_icon(executable, output):
    """Extract the first group icon to PNG, decoding 32-bit Windows DIB if needed.

    The converted trademark asset stays on the user's machine. No dependencies
    beyond Python are needed, and unsupported encodings fail explicitly.
    """
    pe = PE(executable)
    resource_rva = pe.u32(pe.directories + 16)
    if not resource_rva:
        raise Error('Vendor executable has no icon resources.')
    root = pe.offset(resource_rva)

    def entries(relative):
        off = root + relative
        count = pe.u16(off + 12) + pe.u16(off + 14)
        return [struct.unpack_from('<II', pe.data, off + 16 + i * 8) for i in range(count)]

    def child(relative, ident=None):
        values = entries(relative)
        if ident is not None:
            values = [value for value in values if value[0] == ident]
        if not values:
            raise Error('Required icon resource is missing.')
        return values[0][1]

    def blob(entry):
        # Descend through ID/language directories to IMAGE_RESOURCE_DATA_ENTRY.
        while entry & 0x80000000:
            entry = child(entry & 0x7fffffff)
        off = root + entry
        rva, size = struct.unpack_from('<II', pe.data, off)
        data_offset = pe.offset(rva)
        data = pe.data[data_offset:data_offset + size]
        if len(data) != size:
            raise Error('Truncated icon resource.')
        return data

    group = blob(child(0, 14))
    if len(group) < 6 or group[:4] != b'\0\0\1\0':
        raise Error('Invalid Windows group icon.')
    candidates = []
    icons_directory = child(0, 3) & 0x7fffffff
    for i in range(struct.unpack_from('<H', group, 4)[0]):
        width, height, _, _, _, _, size, icon_id = struct.unpack_from('<BBBBHHIH', group, 6 + i * 14)
        image = blob(child(icons_directory, icon_id))
        if len(image) != size:
            raise Error('Icon resource length differs from its group entry.')
        if not image.startswith(b'\x89PNG\r\n\x1a\n'):
            image = dib_to_png(image)
        candidates.append(((width or 256) * (height or 256), image))
    if not candidates:
        raise Error('Vendor executable contains no usable group icon.')
    Path(output).write_bytes(max(candidates, key=lambda item: item[0])[1])


def dib_to_png(data):
    """Convert a bounded 32-bit BI_RGB ICO DIB, including transparency mask."""
    if len(data) < 40:
        raise Error('Truncated icon bitmap.')
    header, width, doubled_height, planes, bits, compression = struct.unpack_from('<IiiHHI', data)
    height = abs(doubled_height) // 2
    if header != 40 or planes != 1 or bits != 32 or compression != 0:
        raise Error('Unsupported icon bitmap format (expected 32-bit BI_RGB).')
    if not 1 <= width <= 1024 or not 1 <= height <= 1024 or abs(doubled_height) % 2:
        raise Error('Invalid icon bitmap dimensions.')
    mask_stride = ((width + 31) // 32) * 4
    pixel_end = header + width * height * 4
    if len(data) < pixel_end + mask_stride * height:
        raise Error('Truncated icon pixels/transparency mask.')
    has_alpha = any(data[header + 3:pixel_end:4])
    rows = bytearray()
    for y in range(height):
        source_y = height - 1 - y if doubled_height > 0 else y
        rows.append(0)  # PNG filter type: none.
        for x in range(width):
            blue, green, red, alpha = data[header + (source_y * width + x) * 4:header + (source_y * width + x) * 4 + 4]
            transparent = data[pixel_end + source_y * mask_stride + x // 8] & (0x80 >> (x % 8))
            rows.extend((red, green, blue, 0 if transparent else alpha if has_alpha else 255))
    def chunk(kind, payload):
        return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(rows), 9)) + chunk(b'IEND', b''))
