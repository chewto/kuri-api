from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(password: str) -> str:
    """Genera un hash seguro para la contraseña provista."""
    return generate_password_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Valida si la contraseña plana coincide con el hash almacenado."""
    return check_password_hash(password_hash, password)
