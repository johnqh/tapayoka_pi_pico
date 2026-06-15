from eth_hash.auto import keccak as keccak_oracle

from src.keccak import keccak256


def test_empty():
    assert keccak256(b"") == keccak_oracle(b"")


def test_known_vectors():
    for msg in [b"abc", b"hello world", b"\x19Ethereum Signed Message:\n5hello", bytes(range(200))]:
        assert keccak256(msg) == keccak_oracle(msg)


def test_returns_32_bytes():
    assert len(keccak256(b"x")) == 32
