import hashlib
import hmac
import os
import struct

MAGIC = b'NSX1'
KEY_LEN = 32
NONCE_LEN = 16
SALT_LEN = 16
ITERATIONS = 200_000


def generate_salt():
    return os.urandom(SALT_LEN).hex()


def derive_key(password, salt_hex):
    salt = bytes.fromhex(salt_hex)
    if isinstance(password, str):
        password = password.encode('utf-8')
    return hashlib.pbkdf2_hmac('sha256', password, salt, ITERATIONS, dklen=KEY_LEN)


def _keystream(key, nonce, length):
    out = b''
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + struct.pack('>Q', counter), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def encrypt_data(data, key):
    nonce = os.urandom(NONCE_LEN)
    ks = _keystream(key, nonce, len(data))
    ciphertext = bytes(a ^ b for a, b in zip(data, ks))
    tag = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    return MAGIC + nonce + ciphertext + tag


def decrypt_data(blob, key):
    if len(blob) < len(MAGIC) + NONCE_LEN + 32:
        raise ValueError('Invalid encrypted data')
    if blob[:4] != MAGIC:
        raise ValueError('Not encrypted data')
    nonce = blob[4:4 + NONCE_LEN]
    ciphertext = blob[4 + NONCE_LEN:-32]
    tag = blob[-32:]
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError('Wrong key or corrupted data')
    ks = _keystream(key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, ks))
