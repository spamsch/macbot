"""
Core Spotlight store.db binary parser.

Parses the proprietary '8tsd' format used by macOS Core Spotlight.
This is an independent, clean-room implementation based on publicly
available documentation and reverse-engineered descriptions of the
on-disk format.

Focused on extracting metadata items (mail messages, etc.) from the
per-user Core Spotlight database.
"""

from __future__ import annotations

import datetime
import logging
import struct
import zlib
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterator

import lz4.block

log = logging.getLogger(__name__)

try:
    import liblzfse
    _lzfse_capable = True
except ImportError:
    _lzfse_capable = False


# ---------------------------------------------------------------------------
# Variable-size number encoding used throughout the format
# ---------------------------------------------------------------------------

def read_var_size_num(data: bytes | memoryview) -> tuple[int, int]:
    """Decode a variable-size integer. Returns (value, bytes_consumed)."""
    first_byte = data[0]
    extra = 0
    use_lower_nibble = True

    if first_byte == 0:
        return 0, 1
    elif (first_byte & 0xF0) == 0xF0:
        use_lower_nibble = False
        if (first_byte & 0x0F) == 0x0F:
            extra = 8
        elif (first_byte & 0x0E) == 0x0E:
            extra = 7
        elif (first_byte & 0x0C) == 0x0C:
            extra = 6
        elif (first_byte & 0x08) == 0x08:
            extra = 5
        else:
            extra = 4
            use_lower_nibble = True
            first_byte -= 0xF0
    elif (first_byte & 0xE0) == 0xE0:
        extra = 3
        first_byte -= 0xE0
    elif (first_byte & 0xC0) == 0xC0:
        extra = 2
        first_byte -= 0xC0
    elif (first_byte & 0x80) == 0x80:
        extra = 1
        first_byte -= 0x80

    if extra:
        num = sum(data[x] << (extra - x) * 8 for x in range(1, extra + 1))
        if use_lower_nibble:
            num += first_byte << (extra * 8)
        return num, extra + 1
    return first_byte, extra + 1


def read_index_var_size_num(data: bytes | memoryview) -> tuple[int, int]:
    """Decode a variable-size integer (index variant with continuation bits)."""
    byte = data[0]
    num_bytes_read = 1
    ret = byte & 0x7F
    while (byte & 0x80) == 0x80:
        byte = data[num_bytes_read]
        ret |= (byte & 0x7F) << (7 * num_bytes_read)
        num_bytes_read += 1
    return ret, num_bytes_read


# ---------------------------------------------------------------------------
# Mac absolute time (2001 epoch) to datetime
# ---------------------------------------------------------------------------

_MAC_EPOCH = datetime.datetime(2001, 1, 1)


def mac_abs_time_to_datetime(value: float) -> datetime.datetime | None:
    if value == 0:
        return None
    try:
        if value > 0 and value > 18446744073709551615:
            return None
        old = value
        value = struct.unpack("<q", struct.pack("<Q", int(value)))[0]
        if int(old) == value:
            value = old
        return _MAC_EPOCH + datetime.timedelta(seconds=value)
    except (ValueError, OverflowError, struct.error):
        return None


def epoch_us_to_datetime(value: int) -> datetime.datetime | None:
    try:
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=value / 1_000_000.0)
    except OverflowError:
        return None


# ---------------------------------------------------------------------------
# Filter language-tagged strings
# ---------------------------------------------------------------------------

import re as _re
_LANG_TAG_RE = _re.compile(b"\x16\x02[^\x00]{0,2}")


def filter_strings(raw: bytes) -> str:
    raw = raw.rstrip(b'\x00')
    try:
        s = _LANG_TAG_RE.sub(b"", raw).rstrip(b"\x00")
        return ", ".join(s.decode('utf8', 'ignore').split('\x00'))
    except ValueError:
        return raw.decode('utf8', 'backslashreplace')


# ---------------------------------------------------------------------------
# Metadata item — one record from the store
# ---------------------------------------------------------------------------

class MetadataItem:
    """A single parsed metadata entry from the Spotlight store."""

    __slots__ = (
        'id', 'flags', 'item_id', 'parent_id', 'date_updated',
        'props', '_data', '_pos', '_size', '_file_pos',
    )

    def __init__(self, file_pos: int, data: bytes, size: int):
        self._file_pos = file_pos
        self._data = data
        self._pos = 0
        self._size = size
        self.props: dict[str, Any] = {}
        self.id = 0
        self.flags = 0
        self.item_id = 0
        self.parent_id = 0
        self.date_updated: int | None = None

    # -- primitive readers --

    def _read_float(self) -> float:
        v = struct.unpack("<f", self._data[self._pos:self._pos + 4])[0]
        self._pos += 4
        return v

    def _read_double(self) -> float:
        v = struct.unpack("<d", self._data[self._pos:self._pos + 8])[0]
        self._pos += 8
        return v

    def _read_date(self) -> datetime.datetime | None:
        return mac_abs_time_to_datetime(self._read_double())

    def _read_var(self) -> tuple[int, int]:
        num, br = read_var_size_num(self._data[self._pos:min(self._size, 9 + self._pos)])
        self._pos += br
        return num, br

    def _read_byte(self) -> int:
        v = self._data[self._pos]
        self._pos += 1
        return v

    def _read_str(self) -> str:
        size, _ = self._read_var()
        raw = self._data[self._pos:self._pos + size]
        if size:
            if raw[-1] == 0:
                raw = raw[:-1]
            if raw.endswith(b'\x16\x02'):
                raw = raw[:-2]
            self._pos += size
        return raw.decode('utf8', 'backslashreplace')

    def _read_strings(self) -> list[str]:
        size, _ = self._read_var()
        blob = self._data[self._pos:self._pos + size]
        parts = [x for x in blob.split(b'\x00') if x != b'']
        result = []
        for x in parts:
            if x.endswith(b'\x16\x02'):
                x = x[:-2]
            result.append(x.decode('utf8', 'backslashreplace'))
        self._pos += size
        return result

    def _read_hex(self, count: int) -> str:
        raw = self._data[self._pos:self._pos + count]
        self._pos += count
        return raw.hex().upper()

    # -- main parse --

    def parse(
        self,
        properties: dict[int, list],
        categories: dict[int, bytes],
        indexes_1: dict[int, tuple[int, ...]],
        indexes_2: dict[int, tuple[int, ...]],
    ) -> None:
        self.id = struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0]
        self.flags = self._read_byte()
        self.item_id = struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0]
        self.parent_id = struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0]
        self.date_updated = self._read_var()[0]

        prop_index = 0
        while self._pos < self._size:
            prop_skip = self._read_var()[0]
            if prop_skip == 0 or prop_skip == 0xFFFFFFFF:
                break

            prop_index += prop_skip
            prop = properties.get(prop_index)
            if prop is None:
                log.debug("Invalid property index %d", prop_index)
                return

            prop_name: str = prop[0]
            prop_type: int = prop[1]
            value_type: int = prop[2]
            value: Any = ''

            try:
                value = self._parse_value(value_type, prop_type, prop_name,
                                          categories, indexes_1, indexes_2)
            except (IndexError, struct.error):
                log.debug("Parse error for prop %s at item %d", prop_name, self.id)
                return

            if value is not None:
                self.props[prop_name] = value

    def _parse_value(
        self,
        value_type: int,
        prop_type: int,
        prop_name: str,
        categories: dict[int, bytes],
        indexes_1: dict[int, tuple[int, ...]],
        indexes_2: dict[int, tuple[int, ...]],
    ) -> Any:
        multi = prop_type & 2 == 2

        if value_type in (0, 2, 6):
            if multi and value_type == 6:
                return [self._read_var()[0] for _ in range(2)]
            return self._read_var()[0]

        if value_type == 7:
            if multi:
                number = struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0]
                n = number >> 3
                return [struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0] for _ in range(n)]
            return struct.unpack("<q", struct.pack("<Q", self._read_var()[0]))[0]

        if value_type == 8:
            if prop_name == 'kMDStoreAccumulatedSizes':
                return None
            if multi:
                return [self._read_var()[0] for _ in range(4)]
            return self._read_var()[0]

        if value_type == 9:
            if multi:
                n = self._read_var()[0] // 4
                return [self._read_float() for _ in range(n)]
            return self._read_float()

        if value_type == 0x0A:
            if multi:
                n = self._read_var()[0] // 8
                return [self._read_double() for _ in range(n)]
            return self._read_double()

        if value_type == 0x0B:
            strings = self._read_strings()
            if not multi:
                return strings[0] if len(strings) == 1 else ('' if not strings else strings)
            return strings

        if value_type == 0x0C:
            if multi:
                n = self._read_var()[0] // 8
                return [self._read_date() for _ in range(n)]
            return self._read_date()

        if value_type == 0x0E:
            if prop_type & 0x80 == 0x80:
                nb = self._read_var()[0]
                if nb > 0:
                    return self._read_hex(nb - 1)
                return ''
            if multi:
                size, _ = self._read_var()
                blob = self._data[self._pos:self._pos + size]
                parts = [x for x in blob.split(b'\x00') if x]
                self._pos += size
                if prop_name == 'kMDStoreProperties':
                    return [p.decode('utf8', 'ignore') for p in parts]
                return [p.decode('utf8', 'ignore') for p in parts]
            size, _ = self._read_var()
            raw = self._data[self._pos:self._pos + size]
            self._pos += size
            if prop_name == 'kMDStoreProperties':
                return raw.decode('utf8', 'ignore')
            return raw.decode('utf8', 'ignore')

        if value_type == 0x0F:
            val = struct.unpack("<i", struct.pack("<I", self._read_var()[0]))[0]
            if val < 0:
                return '' if val == -16777217 else None

            if prop_type & 3 == 3:
                ids = indexes_2.get(val)
                if ids is None:
                    return ''
                for v in ids:
                    if v < 0:
                        continue
                    cat = categories.get(v)
                    if cat:
                        return cat.split(b'\x16\x02')[0].decode('utf8', 'backslashreplace')
                return ''

            if prop_type & 0x2 == 0x2:
                ids = indexes_1.get(val)
                if ids is None:
                    return ''
                tree = []
                for v in ids:
                    if v < 0:
                        continue
                    cat = categories.get(v)
                    if cat:
                        tree.append(cat.decode('utf8', 'backslashreplace'))
                return tree

            cat = categories.get(val)
            if cat:
                return cat.decode('utf8', 'backslashreplace')
            return ''

        return None


# ---------------------------------------------------------------------------
# Block structures
# ---------------------------------------------------------------------------

class BlockType(IntEnum):
    UNKNOWN_0 = 0
    STRINGSV1 = 0x03
    METADATA = 0x09
    PROPERTY = 0x11
    CATEGORY = 0x21
    UNKNOWN_41 = 0x41
    INDEX = 0x81


class _Block0:
    def __init__(self, data: bytes):
        sig = struct.unpack("<I", data[0:4])[0]
        if sig not in (0x64626D31, 0x64626D32):
            raise ValueError(f"Unknown block0 signature: {sig:#x}")
        self.physical_size = struct.unpack("<I", data[4:8])[0]
        self.item_count = struct.unpack("<I", data[8:12])[0]
        self.indexes: list[tuple[int, int, int]] = []
        pos = 20
        for _ in range(self.item_count):
            idx = struct.unpack("<QII", data[pos:pos + 16])
            self.indexes.append(idx)
            pos += 16


class _Block:
    def __init__(self, data: bytes):
        sig = struct.unpack("<I", data[0:4])[0]
        if sig != 0x64627032:
            raise ValueError(f"Unknown block signature: {sig:#x}")
        self.physical_size = struct.unpack("<I", data[4:8])[0]
        self.logical_size = struct.unpack("<I", data[8:12])[0]
        self.block_type = struct.unpack("<I", data[12:16])[0]
        self.unknown = struct.unpack("<I", data[16:20])[0]
        self.next_block_index = struct.unpack("<I", data[20:24])[0]
        self.data = data


# ---------------------------------------------------------------------------
# DbStr map file helpers
# ---------------------------------------------------------------------------

def _read_offsets(data: bytes) -> list[tuple[int, int]]:
    """Parse dbStr-X.map.offsets → list of (index, offset)."""
    offsets = []
    pos = 4
    index = 1
    while pos < len(data):
        off = struct.unpack("<I", data[pos:pos + 4])[0]
        if off == 0:
            break
        if off != 1:
            offsets.append((index, off))
        index += 1
        pos += 4
    return offsets


def _read_map_files(folder: Path, map_id: int) -> tuple[bytes, bytes, bytes]:
    """Read dbStr-{map_id}.map.{data,offsets,header} files."""
    return (
        (folder / f'dbStr-{map_id}.map.data').read_bytes(),
        (folder / f'dbStr-{map_id}.map.offsets').read_bytes(),
        (folder / f'dbStr-{map_id}.map.header').read_bytes(),
    )


# ---------------------------------------------------------------------------
# Main store reader
# ---------------------------------------------------------------------------

class SpotlightStoreReader:
    """Reads a Core Spotlight store.db file and yields MetadataItem objects."""

    def __init__(self, store_path: Path):
        self._path = store_path
        self._folder = store_path.parent
        self._properties: dict[int, list] = {}
        self._categories: dict[int, bytes] = {}
        self._indexes_1: dict[int, tuple[int, ...]] = {}
        self._indexes_2: dict[int, tuple[int, ...]] = {}
        self._block0: _Block0 | None = None

        self._f = open(store_path, 'rb')  # noqa: SIM115
        self._file_size = store_path.stat().st_size

        # Read & validate header
        header = self._f.read(0x1000)
        sig = header[0:4]
        if sig not in (b'\x37\x74\x73\x64', b'\x38\x74\x73\x64'):
            self._f.close()
            raise ValueError(f"Not a Spotlight store.db: {sig!r}")

        self._version = 2 if sig == b'\x38\x74\x73\x64' else 1
        self._header = header

        if self._version == 2:
            self._header_size = struct.unpack("<I", header[36:40])[0]
            self._block0_size = struct.unpack("<I", header[40:44])[0]
            self._block_size = struct.unpack("<I", header[44:48])[0]
            self._idx_prop = struct.unpack("<I", header[48:52])[0]
            self._idx_cat = struct.unpack("<I", header[52:56])[0]
            self._idx_41 = struct.unpack("<I", header[56:60])[0]
            self._idx_81_1 = struct.unpack("<I", header[60:64])[0]
            self._idx_81_2 = struct.unpack("<I", header[64:68])[0]
            self._is_ios = self._idx_prop == 0
        else:
            self._header_size = struct.unpack("<I", header[40:44])[0]
            self._block0_size = struct.unpack("<I", header[44:48])[0]
            self._block_size = struct.unpack("<I", header[48:52])[0]
            self._is_ios = False

    def close(self) -> None:
        self._f.close()

    def __enter__(self) -> SpotlightStoreReader:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # -- internal I/O --

    def _seek(self, pos: int) -> None:
        self._f.seek(pos)

    def _read(self, size: int) -> bytes:
        return self._f.read(size)

    # -- definition parsing --

    def _parse_block_sequence(self, initial_index: int, block_type: int,
                              handler: Any) -> None:
        if initial_index == 0:
            return
        self._seek(initial_index * 0x1000)
        data = self._read(self._block_size)
        block = _Block(data)
        if block.block_type != block_type:
            raise ValueError(f"Expected block type {block_type:#x}, got {block.block_type:#x}")
        handler(block)
        while block.next_block_index != 0:
            self._seek(block.next_block_index * 0x1000)
            data = self._read(self._block_size)
            block = _Block(data)
            handler(block)

    def _parse_properties_block(self, block: _Block) -> None:
        data = block.data
        pos = 32
        size = block.logical_size
        while pos < size:
            index, value_type, prop_type = struct.unpack("<IBB", data[pos:pos + 6])
            pos += 6
            name = data[pos:pos + size].split(b'\x00')[0]
            pos += len(name) + 1 if len(name) < size else size
            self._properties[index] = [name.decode('utf-8', 'backslashreplace'), prop_type, value_type]

    def _parse_categories_block(self, block: _Block) -> None:
        data = block.data
        pos = 32
        size = block.logical_size
        while pos < size:
            index = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
            name = data[pos:pos + size].split(b'\x00')[0]
            pos += len(name) + 1 if len(name) < size else size
            self._categories[index] = name

    def _parse_indexes_block(self, block: _Block, dictionary: dict) -> None:
        data = block.data
        data_len = len(data)
        pos = 32
        size = block.logical_size
        while pos < size:
            index = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
            index_size, br = read_var_size_num(data[pos:min(pos + 9, data_len)])
            pos += br
            padding = index_size % 4
            pos += padding
            index_size = 4 * (index_size // 4)
            ids = struct.unpack("<" + str(index_size // 4) + "i", data[pos:pos + index_size])
            pos += index_size
            dictionary[index] = ids

    def _parse_from_file_data(self, map_data: bytes, map_offsets: bytes,
                               map_header: bytes, target: dict,
                               parser: str, has_extra_byte: bool = False) -> None:
        offsets = _read_offsets(map_offsets)
        data_len = len(map_data)
        for index, offset in offsets:
            if offset >= data_len:
                continue
            entry_size, esb = read_var_size_num(map_data[offset:min(offset + 9, data_len)])
            if parser == 'properties':
                value_type, prop_type = struct.unpack("<BB", map_data[offset + esb:offset + esb + 2])
                name = map_data[offset + esb + 2:offset + esb + entry_size].split(b'\x00')[0]
                target[index] = [name.decode('utf-8', 'backslashreplace'), prop_type, value_type]
            elif parser == 'categories':
                name = map_data[offset + esb:offset + esb + entry_size].split(b'\x00')[0]
                target[index] = name
            elif parser == 'indexes':
                pos = offset
                # Read entry_size using the index variant (continuation-bit encoding)
                entry_size_val, entry_size_bytes = read_index_var_size_num(
                    map_data[pos:min(pos + 9, data_len)])
                pos += entry_size_bytes
                # Read index_size using standard var-size encoding
                idx_size, br = read_var_size_num(map_data[pos:min(pos + 9, data_len)])
                pos += br
                if has_extra_byte:
                    pos += 1
                idx_size = 4 * (idx_size // 4)
                if idx_size > 0 and pos + idx_size <= data_len:
                    ids = struct.unpack("<" + str(idx_size // 4) + "i",
                                       map_data[pos:pos + idx_size])
                    target[index] = ids

    def _load_definitions(self) -> None:
        """Load property definitions, categories, and indexes."""
        self._seek(self._header_size)
        block0_data = self._read(self._block0_size)
        self._block0 = _Block0(block0_data)

        if self._is_ios:
            # External dbStr files (iOS / per-user CoreSpotlight)
            d, o, h = _read_map_files(self._folder, 1)
            self._parse_from_file_data(d, o, h, self._properties, 'properties')
            d, o, h = _read_map_files(self._folder, 2)
            self._parse_from_file_data(d, o, h, self._categories, 'categories')
            d, o, h = _read_map_files(self._folder, 4)
            self._parse_from_file_data(d, o, h, self._indexes_1, 'indexes')
            d, o, h = _read_map_files(self._folder, 5)
            self._parse_from_file_data(d, o, h, self._indexes_2, 'indexes', has_extra_byte=True)
        else:
            self._parse_block_sequence(self._idx_prop, BlockType.PROPERTY, self._parse_properties_block)
            self._parse_block_sequence(self._idx_cat, BlockType.CATEGORY, self._parse_categories_block)
            self._parse_block_sequence(self._idx_81_1, BlockType.INDEX,
                                       lambda b: self._parse_indexes_block(b, self._indexes_1))
            self._parse_block_sequence(self._idx_81_2, BlockType.INDEX,
                                       lambda b: self._parse_indexes_block(b, self._indexes_2))

    def _decompress_block(self, block_data: bytes, block: _Block) -> bytes | None:
        try:
            if block.block_type & 0x1000 == 0x1000:  # LZ4
                if block_data[20:24] in (b'bv41', b'bv4-'):
                    chunk_start = 20
                    uncompressed = b''
                    last_uncompressed = b''
                    header = block_data[chunk_start:chunk_start + 4]
                    while self._block_size > chunk_start and header != b'bv4$':
                        if header == b'bv41':
                            us, cs = struct.unpack('<II', block_data[chunk_start + 4:chunk_start + 12])
                            last_uncompressed = lz4.block.decompress(
                                block_data[chunk_start + 12:chunk_start + 12 + cs],
                                us, dict=last_uncompressed)
                            chunk_start += 12 + cs
                            uncompressed += last_uncompressed
                        elif header == b'bv4-':
                            us = struct.unpack('<I', block_data[chunk_start + 4:chunk_start + 8])[0]
                            uncompressed += block_data[chunk_start + 8:chunk_start + 8 + us]
                            chunk_start += 8 + us
                        else:
                            break
                        header = block_data[chunk_start:chunk_start + 4]
                    return uncompressed
                return lz4.block.decompress(
                    block_data[20:block.logical_size],
                    block.unknown - 20)

            if block.block_type & 0x2000 == 0x2000:  # LZFSE
                if not _lzfse_capable:
                    log.warning("LZFSE block skipped — liblzfse not installed")
                    return None
                if block_data[20:23] == b'bvx':
                    header = block_data[20:24]
                    if header in (b'bvx1', b'bvx2', b'bvxn'):
                        return liblzfse.decompress(block_data[20:block.logical_size])
                    if header == b'bvx-':
                        us = struct.unpack('<I', block_data[24:28])[0]
                        return block_data[28:28 + us]
                return lz4.block.decompress(
                    block_data[20:block.logical_size],
                    block.unknown - 20)

            # zlib
            return zlib.decompressobj().decompress(block_data[20:block.logical_size])
        except Exception:
            log.debug("Decompression error", exc_info=True)
            return None

    # -- public API --

    def iter_items(self) -> Iterator[MetadataItem]:
        """Iterate all metadata items in the store."""
        self._load_definitions()
        assert self._block0 is not None

        for index in self._block0.indexes:
            seek_offset = index[1] * 0x1000
            if seek_offset >= self._file_size:
                continue
            self._seek(seek_offset)
            block_data = self._read(self._block_size)

            try:
                block = _Block(block_data)
            except ValueError:
                continue

            if block.block_type & 0xFF != BlockType.METADATA:
                continue

            uncompressed = self._decompress_block(block_data, block)
            if not uncompressed:
                continue

            pos = 0
            meta_size = len(uncompressed)
            while pos < meta_size:
                item_size = struct.unpack("<I", uncompressed[pos:pos + 4])[0]
                item = MetadataItem(pos + 4, uncompressed[pos + 4:pos + 4 + item_size], item_size)
                try:
                    item.parse(self._properties, self._categories,
                              self._indexes_1, self._indexes_2)
                except (KeyError, ValueError, OSError):
                    log.debug("Error parsing item at offset %d", pos, exc_info=True)
                else:
                    yield item
                pos += item_size + 4
