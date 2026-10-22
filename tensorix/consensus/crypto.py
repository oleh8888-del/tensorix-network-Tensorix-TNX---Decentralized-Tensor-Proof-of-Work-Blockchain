"""
Tensorix Network (TNX) - Cryptographic Primitives
Ed25519 for transactions & identities, BLAKE3 for consensus hashing.
"""

import hashlib
import binascii
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature

import blake3


def hash256(data: bytes) -> bytes:
    """Consensus hashing must not change with installed optional packages."""
    return blake3.blake3(data).digest()


def hash256_hex(data: bytes) -> str:
    """Hexadecimal representation of 256-bit hash."""
    return hash256(data).hex()


def double_hash256(data: bytes) -> bytes:
    """Double hash for Merkle tree nodes and header validation."""
    return hash256(hash256(data))


def generate_keypair():
    """Generate a new Ed25519 private/public keypair."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    
    address = pub_to_address(pub_bytes)
    return priv_bytes.hex(), pub_bytes.hex(), address


def pub_to_address(pub_bytes: bytes) -> str:
    """Encode 32-byte public key into TNX address format: tnx1<checksum_hex>."""
    h = hashlib.sha256(pub_bytes).digest()[:20]
    return f"tnx1{h.hex()}"


def sign_message(private_key_hex: str, message: bytes) -> str:
    """Sign arbitrary binary payload using Ed25519 private key."""
    priv_bytes = bytes.fromhex(private_key_hex)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
    signature = private_key.sign(message)
    return signature.hex()


def verify_signature(public_key_hex: str, message: bytes, signature_hex: str) -> bool:
    """Verify Ed25519 signature."""
    try:
        pub_bytes = bytes.fromhex(public_key_hex)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, message)
        return True
    except (InvalidSignature, ValueError, binascii.Error):
        return False

