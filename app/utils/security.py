from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(password: str) -> str:
    """Generates a secure hash for the provided password."""
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Checks whether the plain-text password matches the stored hash."""
    return check_password_hash(password_hash, password)
