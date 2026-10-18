"""Generate an Argon2id hash locally; plaintext input is never echoed."""

import getpass
from argon2 import PasswordHasher

password = getpass.getpass("Owner password (12+ characters): ")
if len(password) < 12:
    raise SystemExit("Use at least 12 characters")
print(PasswordHasher().hash(password))
