#!/usr/bin/env python3
"""
Cryptkeeper Lite - Standalone Jasypt-compatible encryption/decryption tool
No Docker required!

This replicates the functionality of the cryptkeeper Docker image using pure Python.
Uses PBEWithMD5AndDES algorithm (Jasypt default) for compatibility.
"""

import sys
import os
import re
import base64
import hashlib
from Crypto.Cipher import DES


def generate_key_iv(password: str, salt: bytes, iterations: int = 1000) -> tuple:
    """
    Generate key and IV using PKCS5 (PBKDF1) with MD5.
    This matches Jasypt's PBEWithMD5AndDES algorithm.
    
    Args:
        password: Password string
        salt: 8-byte salt
        iterations: Number of iterations (default 1000)
    
    Returns:
        Tuple of (key, iv) where key is 8 bytes and iv is 8 bytes
    """
    # PBKDF1 with MD5 (for PBEWithMD5AndDES compatibility)
    password_bytes = password.encode('utf-8')
    
    # First iteration
    md5 = hashlib.md5()
    md5.update(password_bytes)
    md5.update(salt)
    derived = md5.digest()
    
    # Remaining iterations
    for _ in range(1, iterations):
        md5 = hashlib.md5()
        md5.update(derived)
        derived = md5.digest()
    
    # First 8 bytes = DES key, next 8 bytes = IV
    key = derived[0:8]
    iv = derived[8:16]
    
    return key, iv


def pkcs5_pad(data: bytes) -> bytes:
    """Add PKCS5 padding to data"""
    padding_len = 8 - (len(data) % 8)
    padding = bytes([padding_len] * padding_len)
    return data + padding


def pkcs5_unpad(data: bytes) -> bytes:
    """Remove PKCS5 padding from data"""
    padding_len = data[-1]
    return data[:-padding_len]


def encrypt_value(plaintext: str, password: str) -> str:
    """
    Encrypt a plaintext value using Jasypt-compatible PBEWithMD5AndDES.
    
    Args:
        plaintext: Plain text to encrypt
        password: Encryption password/key
    
    Returns:
        Encrypted value in format: ENC(base64_encoded_value)
    """
    # Generate random 8-byte salt
    salt = os.urandom(8)
    
    # Derive key and IV
    key, iv = generate_key_iv(password, salt)
    
    # Encrypt
    cipher = DES.new(key, DES.MODE_CBC, iv)
    plaintext_bytes = plaintext.encode('utf-8')
    padded = pkcs5_pad(plaintext_bytes)
    encrypted = cipher.encrypt(padded)
    
    # Format: salt + encrypted_data
    result = salt + encrypted
    
    # Base64 encode
    encoded = base64.b64encode(result).decode('ascii')
    
    return f"ENC({encoded})"


def decrypt_value(encrypted: str, password: str) -> str:
    """
    Decrypt a Jasypt-encrypted value.
    
    Args:
        encrypted: Encrypted value (with or without ENC() wrapper)
        password: Decryption password/key
    
    Returns:
        Decrypted plaintext string
    """
    # Remove ENC() wrapper if present
    encrypted = encrypted.strip()
    if encrypted.startswith('ENC(') and encrypted.endswith(')'):
        encrypted = encrypted[4:-1]
    
    # Base64 decode
    try:
        decoded = base64.b64decode(encrypted)
    except Exception as e:
        raise ValueError(f"Invalid base64 encoding: {e}")
    
    if len(decoded) < 16:
        raise ValueError("Encrypted value too short (must be at least 16 bytes)")
    
    # Extract salt and encrypted data
    salt = decoded[0:8]
    encrypted_data = decoded[8:]
    
    # Derive key and IV
    key, iv = generate_key_iv(password, salt)
    
    # Decrypt
    cipher = DES.new(key, DES.MODE_CBC, iv)
    decrypted_padded = cipher.decrypt(encrypted_data)
    
    # Remove padding
    decrypted = pkcs5_unpad(decrypted_padded)

    try:
        return decrypted.decode('utf-8')
    except UnicodeDecodeError:
        # Try latin-1 as fallback (handles ISO-8859-1 encoded values)
        try:
            return decrypted.decode('latin-1')
        except UnicodeDecodeError:
            raise ValueError(
                "Decryption produced invalid text — the key may be incorrect or the value may be corrupted"
            )


def decrypt_file(input_file: str, output_file: str, password: str, debug: bool = False):
    """
    Decrypt all ENC(...) values in a file.
    
    Args:
        input_file: Path to encrypted file
        output_file: Path to write decrypted file
        password: Decryption password/key
        debug: If True, print decrypted content to stdout
    """
    with open(input_file, 'r') as f:
        content = f.read()
    
    # Find all ENC(...) patterns
    pattern = r'ENC\([A-Za-z0-9+/=]+\)'
    
    def replace_encrypted(match):
        encrypted_value = match.group(0)
        try:
            decrypted = decrypt_value(encrypted_value, password)
            return decrypted
        except Exception as e:
            print(f"Warning: Failed to decrypt {encrypted_value}: {e}", file=sys.stderr)
            return encrypted_value  # Keep original if decryption fails
    
    decrypted_content = re.sub(pattern, replace_encrypted, content)
    
    with open(output_file, 'w') as f:
        f.write(decrypted_content)
    
    print(f"Decrypted {input_file} -> {output_file}")
    
    if debug:
        print("\n--- Decrypted content ---")
        print(decrypted_content)


def print_usage():
    """Print usage information"""
    print("""Usage:
  cryptkeeper_lite.py encrypt-value (expects CRYPTKEEPER_KEY and CRYPTKEEPER_VALUE to be set)
  
  cryptkeeper_lite.py decrypt-value (expects CRYPTKEEPER_KEY and CRYPTKEEPER_VALUE to be set)
  
  cryptkeeper_lite.py decrypt-file <output_dir> <encrypted_file1> [encrypted_file2, ...]
      (expects CRYPTKEEPER_KEY to be set)

NOTE:
  - All options require that the environment variable CRYPTKEEPER_KEY contain the symmetric key.
  - The *-value options require that CRYPTKEEPER_VALUE contain the plaintext/encrypted value.
  - When using decrypt-file, setting DEBUG=true will also dump the decrypted file to stdout.

Examples:
  # Encrypt a value
  CRYPTKEEPER_KEY="mypassword" CRYPTKEEPER_VALUE="secret123" ./cryptkeeper_lite.py encrypt-value
  
  # Decrypt a value
  CRYPTKEEPER_KEY="mypassword" CRYPTKEEPER_VALUE="ENC(abc...)" ./cryptkeeper_lite.py decrypt-value
  
  # Decrypt files
  CRYPTKEEPER_KEY="mypassword" ./cryptkeeper_lite.py decrypt-file /tmp application.yml
""")


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    
    command = sys.argv[1]
    
    # Get password from environment
    password = os.getenv('CRYPTKEEPER_KEY')
    if not password:
        print("ERROR: CRYPTKEEPER_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    
    try:
        if command == 'encrypt-value':
            value = os.getenv('CRYPTKEEPER_VALUE')
            if not value:
                print("ERROR: CRYPTKEEPER_VALUE environment variable not set", file=sys.stderr)
                sys.exit(1)
            
            encrypted = encrypt_value(value, password)
            print(encrypted)
        
        elif command == 'decrypt-value':
            value = os.getenv('CRYPTKEEPER_VALUE')
            if not value:
                print("ERROR: CRYPTKEEPER_VALUE environment variable not set", file=sys.stderr)
                sys.exit(1)
            
            decrypted = decrypt_value(value, password)
            print(decrypted)
        
        elif command == 'decrypt-file':
            if len(sys.argv) < 4:
                print("ERROR: decrypt-file requires output_dir and at least one input file", file=sys.stderr)
                print_usage()
                sys.exit(1)
            
            output_dir = sys.argv[2]
            input_files = sys.argv[3:]
            debug = os.getenv('DEBUG', '').lower() == 'true'
            
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            for input_file in input_files:
                output_file = os.path.join(output_dir, os.path.basename(input_file))
                decrypt_file(input_file, output_file, password, debug)
        
        else:
            print(f"ERROR: Unknown command: {command}", file=sys.stderr)
            print_usage()
            sys.exit(1)
    
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
