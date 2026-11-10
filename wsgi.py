import os
from app import create_app
from app.extensions import db
from app.models import Tenant, User, UserRole

environment = os.getenv("FLASK_ENV", "development")
app = create_app(environment)


@app.shell_context_processor
def make_shell_context():
    """Expose models and db to the interactive 'flask shell' console."""
    return {"db": db, "Tenant": Tenant, "User": User, "UserRole": UserRole}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
