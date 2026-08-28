"""
Secret Protector - Portable native static encryption using AES-256-GCM.

High Cohesion: Single responsibility for encryption/decryption operations
Low Coupling: No external dependencies beyond cryptography library
Type Safety: Full type hints with strict validation

Security Model:
- Current format: nsec2:<base64(nonce(12) | ciphertext | tag(16))>
- Config key used as AES-GCM AAD (Additional Authenticated Data)
- Same ciphertext cannot be copied to another config key
- Legacy nsec1: and enc:dpapi: formats supported for read-only migration
"""

from __future__ import annotations

import base64
import os
from typing import Final

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretProtector:
    """
    Static encryption utility for sensitive configuration values.
    
    Security boundaries:
    - Protects against nori.db being copied alone
    - Does NOT protect against processes that can read application
      memory or keychain under the same user account
    """
    
    # Current format prefix
    PREFIX: Final[str] = "nsec2:"
    NSEC2_PREFIX: Final[str] = PREFIX
    
    # Legacy AES-GCM format prefix (read-only compatible, no AAD)
    LEGACY_NSEC1_PREFIX: Final[str] = "nsec1:"
    
    # Legacy DPAPI format prefix (read-only compatible)
    LEGACY_DPAPI_PREFIX: Final[str] = "enc:dpapi:"
    
    # Cryptographic constants
    NONCE_SIZE: Final[int] = 12
    TAG_SIZE: Final[int] = 16
    
    @classmethod
    def is_protected(cls, stored: str) -> bool:
        """Check if value is nsec1 or nsec2 encrypted."""
        return cls.is_nsec1(stored) or cls.is_nsec2(stored)
    
    @classmethod
    def is_nsec2(cls, stored: str | None) -> bool:
        """Check if value is current nsec2 encrypted."""
        return stored is not None and stored.startswith(cls.NSEC2_PREFIX)
    
    @classmethod
    def is_nsec1(cls, stored: str | None) -> bool:
        """Check if value is legacy nsec1 encrypted."""
        return stored is not None and stored.startswith(cls.LEGACY_NSEC1_PREFIX)
    
    @classmethod
    def is_legacy_dpapi(cls, stored: str | None) -> bool:
        """Check if value is legacy DPAPI encrypted."""
        return stored is not None and stored.startswith(cls.LEGACY_DPAPI_PREFIX)
    
    @classmethod
    def protect(cls, key: bytes, config_key: str, plain_text: str) -> str:
        """
        Encrypt plaintext using current nsec2 format with config key as AAD.
        
        Args:
            key: 32-byte AES-256 key
            config_key: Configuration key to use as AAD
            plain_text: Plaintext to encrypt
            
        Returns:
            Encrypted value with nsec2: prefix
        """
        return cls._protect_v2(key, config_key, plain_text)
    
    @classmethod
    def _protect_v2(cls, key: bytes, config_key: str, plain_text: str) -> str:
        """Encrypt using nsec2 format with AAD."""
        if not plain_text:
            return plain_text
        
        nonce = os.urandom(cls.NONCE_SIZE)
        aad = config_key.encode('utf-8') if config_key else b''
        
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plain_text.encode('utf-8'), aad)
        
        # Ciphertext includes tag at the end
        return cls.PREFIX + cls._encode_payload(nonce, ciphertext[:-cls.TAG_SIZE], ciphertext[-cls.TAG_SIZE:])
    
    @classmethod
    def _protect_v1(cls, key: bytes, plain_text: str) -> str:
        """
        Encrypt using legacy nsec1 format (no AAD).
        Only for migration testing and compatibility.
        """
        if not plain_text:
            return plain_text
        
        nonce = os.urandom(cls.NONCE_SIZE)
        
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plain_text.encode('utf-8'), None)
        
        return cls.LEGACY_NSEC1_PREFIX + cls._encode_payload(nonce, ciphertext[:-cls.TAG_SIZE], ciphertext[-cls.TAG_SIZE:])
    
    @classmethod
    def try_unprotect(cls, key: bytes, stored: str, config_key: str = "") -> tuple[bool, str]:
        """
        Decrypt value, supporting both nsec1 and nsec2 formats.
        
        Args:
            key: 32-byte AES-256 key
            stored: Encrypted value with prefix
            config_key: Configuration key for AAD (required for nsec2)
            
        Returns:
            Tuple of (success, plaintext)
        """
        if cls.is_nsec2(stored):
            return cls._try_unprotect_v2(key, config_key, stored)
        return cls._try_unprotect_v1(key, stored)
    
    @classmethod
    def _try_unprotect_v2(cls, key: bytes, config_key: str, stored: str) -> tuple[bool, str]:
        """Decrypt nsec2 format with AAD."""
        return cls._try_decrypt(key, config_key.encode('utf-8') if config_key else b'', stored, cls.NSEC2_PREFIX)
    
    @classmethod
    def _try_unprotect_v1(cls, key: bytes, stored: str) -> tuple[bool, str]:
        """Decrypt legacy nsec1 format without AAD."""
        return cls._try_decrypt(key, b'', stored, cls.LEGACY_NSEC1_PREFIX)
    
    @classmethod
    def _try_decrypt(
        cls,
        key: bytes,
        aad: bytes,
        stored: str,
        prefix: str,
    ) -> tuple[bool, str]:
        """Generic decryption routine."""
        if not stored.startswith(prefix):
            return False, ""
        
        try:
            payload = base64.b64decode(stored[len(prefix):])
            
            if len(payload) < cls.NONCE_SIZE + cls.TAG_SIZE:
                return False, ""
            
            cipher_length = len(payload) - cls.NONCE_SIZE - cls.TAG_SIZE
            nonce = payload[:cls.NONCE_SIZE]
            cipher_and_tag = payload[cls.NONCE_SIZE:cls.NONCE_SIZE + cipher_length + cls.TAG_SIZE]
            
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, cipher_and_tag, aad)
            
            return True, plaintext.decode('utf-8')
        except Exception:
            return False, ""
    
    @classmethod
    def _encode_payload(cls, nonce: bytes, cipher: bytes, tag: bytes) -> str:
        """Encode nonce | ciphertext | tag as base64."""
        payload = nonce + cipher + tag
        return base64.b64encode(payload).decode('ascii')
