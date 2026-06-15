"""Pure-Python Keccak-256 (Ethereum variant). MicroPython-compatible."""

_RC = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)

# Rotation offsets indexed [x][y].
_R = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)

_MASK = (1 << 64) - 1


def _rol(value, shift):
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _keccak_f(lanes):
    for rnd in range(24):
        # theta
        C = [lanes[x] ^ lanes[x + 5] ^ lanes[x + 10] ^ lanes[x + 15] ^ lanes[x + 20] for x in range(5)]
        D = [C[(x + 4) % 5] ^ _rol(C[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(0, 25, 5):
                lanes[x + y] ^= D[x]
        # rho + pi
        B = [0] * 25
        for x in range(5):
            for y in range(5):
                B[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(lanes[x + 5 * y], _R[x][y])
        # chi
        for x in range(5):
            for y in range(0, 25, 5):
                lanes[x + y] = B[x + y] ^ ((~B[(x + 1) % 5 + y]) & B[(x + 2) % 5 + y]) & _MASK
        # iota
        lanes[0] ^= _RC[rnd]
    return lanes


def keccak256(data):
    rate = 136  # bytes (1088 bits) for 256-bit output
    msg = bytearray(data)
    msg.append(0x01)
    while len(msg) % rate != 0:
        msg.append(0x00)
    msg[-1] ^= 0x80

    state = bytearray(200)
    for off in range(0, len(msg), rate):
        for i in range(rate):
            state[i] ^= msg[off + i]
        lanes = [int.from_bytes(state[8 * j:8 * j + 8], "little") for j in range(25)]
        lanes = _keccak_f(lanes)
        for j in range(25):
            state[8 * j:8 * j + 8] = lanes[j].to_bytes(8, "little")
    return bytes(state[:32])
