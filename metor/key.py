import hashlib
import os
import nacl.bindings

from metor.profile import ProfileManager

class KeyManager:
    """Manages Ed25519 cryptographic keys."""
    
    def __init__(self, pm: ProfileManager):
        self.pm = pm
        self.hs_dir = self.pm.get_hidden_service_dir()

    def generate_keys(self):
        metor_key_path = os.path.join(self.hs_dir, "metor_secret.key")
        tor_sec_path = os.path.join(self.hs_dir, "hs_ed25519_secret_key")
        tor_pub_path = os.path.join(self.hs_dir, "hs_ed25519_public_key")
        
        if os.path.exists(metor_key_path) and os.path.exists(tor_sec_path):
            return

        seed = os.urandom(32)
        public_key, pynacl_secret_key = nacl.bindings.crypto_sign_seed_keypair(seed)
        
        h = hashlib.sha512(seed).digest()
        scalar = bytearray(h[:32])
        scalar[0] &= 248
        scalar[31] &= 127
        scalar[31] |= 64
        expanded_key = bytes(scalar) + h[32:]
        
        with open(metor_key_path, "wb") as f:
            f.write(pynacl_secret_key)
        with open(tor_sec_path, "wb") as f:
            f.write(b"== ed25519v1-secret: type0 ==\x00\x00\x00")
            f.write(expanded_key)
        with open(tor_pub_path, "wb") as f:
            f.write(b"== ed25519v1-public: type0 ==\x00\x00\x00")
            f.write(public_key)

    def get_metor_key(self):
        key_path = os.path.join(self.hs_dir, "metor_secret.key")
        with open(key_path, "rb") as f:
            return f.read()
