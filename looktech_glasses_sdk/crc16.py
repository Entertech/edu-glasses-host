"""CRC-16 used by the EDU-CTRL frame protocol.

This is an exact Python port of the firmware's CRC routine: the classic
table-less "byte swap" variant of CRC-16/CCITT-FALSE (polynomial 0x1021,
initial value 0xFFFF, no reflection, no final XOR)::

    uint16_t crc = 0xFFFF;
    while (size--) {
        crc = (crc >> 8) | (crc << 8);
        crc ^= *buffer++;
        crc ^= ((unsigned char)crc) >> 4;
        crc ^= crc << 12;
        crc ^= (crc & 0xFF) << 5;
    }

In C all intermediate values are truncated to 16 bits because ``crc`` is a
``uint16_t``; in Python we must mask with ``0xFFFF`` by hand.
"""


def crc16(data: bytes, init: int = 0xFFFF) -> int:
    """Compute the firmware CRC-16 over *data*.

    :param data: bytes to checksum (for EDU-CTRL frames: ver..payload,
        i.e. everything between the two sync bytes and the trailing CRC).
    :param init: initial register value (the firmware always uses 0xFFFF).
    :return: 16-bit CRC as an int (0..0xFFFF).
    """
    crc = init & 0xFFFF
    for byte in data:
        # crc = (crc >> 8) | (crc << 8);  -- 16-bit byte swap
        crc = ((crc >> 8) | (crc << 8)) & 0xFFFF
        # crc ^= *buffer++;
        crc ^= byte
        # crc ^= ((unsigned char)crc) >> 4;
        crc ^= (crc & 0xFF) >> 4
        # crc ^= crc << 12;               -- truncated to 16 bits in C
        crc ^= (crc << 12) & 0xFFFF
        # crc ^= (crc & 0xFF) << 5;       -- max 0x1FE0, still fits 16 bits
        crc ^= ((crc & 0xFF) << 5) & 0xFFFF
    return crc
