from app import create_app

app = create_app('testing')
client = app.test_client()

# Register tenant and admin
payload = {
    "tenant_name": "Acme Corp",
    "email": "admin@acme.com",
    "password": "Password123!",
    "plan": "free"
}
reg = client.post('/api/auth/register-tenant', json=payload)
print('register status', reg.status_code)
print('register body', reg.get_json())

# Login
login = client.post('/api/auth/login', json={"email": "admin@acme.com", "password": "Password123!"})
print('login status', login.status_code)
print('login body', login.get_json())
