"""Minimal secp256k1 ECDSA (sign + recover) for MicroPython.

Uses Python arbitrary-precision ints and modular pow for inverses.
"""

import os

from .keccak import keccak256

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _inv(a, m):
    return pow(a % m, m - 2, m)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if x1 == x2 and y1 == y2:
        m = (3 * x1 * x1) * _inv(2 * y1, P) % P
    else:
        m = (y2 - y1) * _inv((x2 - x1) % P, P) % P
    x3 = (m * m - x1 - x2) % P
    y3 = (m * (x1 - x3) - y1) % P
    return (x3, y3)


def _mul(k, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def privkey_to_pubkey(priv):
    d = int.from_bytes(priv, "big")
    return _mul(d, (GX, GY))


def _hex(b):
    return "".join("{:02x}".format(x) for x in b)


def pubkey_to_address(x, y):
    pub = x.to_bytes(32, "big") + y.to_bytes(32, "big")
    return "0x" + _hex(keccak256(pub)[-20:])


def sign(msg_hash, priv):
    z = int.from_bytes(msg_hash, "big")
    d = int.from_bytes(priv, "big")
    while True:
        k = int.from_bytes(os.urandom(32), "big") % N
        if k == 0:
            continue
        rp = _mul(k, (GX, GY))
        r = rp[0] % N
        if r == 0:
            continue
        s = (_inv(k, N) * (z + r * d)) % N
        if s == 0:
            continue
        rec = (rp[1] & 1) | (2 if rp[0] >= N else 0)
        if s > N // 2:
            s = N - s
            rec ^= 1
        return (r, s, 27 + rec)


def recover(msg_hash, r, s, v):
    z = int.from_bytes(msg_hash, "big")
    rec = v - 27
    x = r + (N if (rec & 2) else 0)
    y2 = (pow(x, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if (y & 1) != (rec & 1):
        y = P - y
    rp = (x, y)
    r_inv = _inv(r, N)
    u1 = (-z * r_inv) % N
    u2 = (s * r_inv) % N
    return _add(_mul(u1, (GX, GY)), _mul(u2, rp))
