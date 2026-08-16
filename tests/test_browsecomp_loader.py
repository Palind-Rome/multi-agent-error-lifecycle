"""Offline tests for the BrowseComp decrypt/load logic (no network)."""

from __future__ import annotations

import base64
import unittest

from mas_error_lifecycle.adapters.browsecomp_loader import _derive_key, decrypt


def _encrypt(plaintext: str, password: str) -> str:
    key = _derive_key(password, len(plaintext.encode()))
    encrypted = bytes(a ^ b for a, b in zip(plaintext.encode(), key))
    return base64.b64encode(encrypted).decode()


class DecryptTests(unittest.TestCase):
    def test_derive_key_is_deterministic_and_length_matched(self):
        self.assertEqual(_derive_key("abc", 10), _derive_key("abc", 10))
        self.assertEqual(len(_derive_key("abc", 10)), 10)
        self.assertEqual(len(_derive_key("abc", 64)), 64)
        self.assertNotEqual(_derive_key("abc", 32), _derive_key("abd", 32))

    def test_decrypt_round_trip(self):
        for plaintext, password in [
            ("1988-96", "canary-1"),
            ("A longer question with Unicode: 北京 300.00s", "row-42"),
        ]:
            ciphertext = _encrypt(plaintext, password)
            self.assertEqual(decrypt(ciphertext, password), plaintext)

    def test_wrong_password_does_not_recover_plaintext(self):
        ciphertext = _encrypt("secret", "right-password")
        try:
            result = decrypt(ciphertext, "wrong-password")
        except UnicodeDecodeError:
            return  # wrong key produces invalid UTF-8 -> also not the plaintext
        self.assertNotEqual(result, "secret")


if __name__ == "__main__":
    unittest.main()
