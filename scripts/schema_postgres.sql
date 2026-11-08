-- Esquema PostgreSQL del CRM, generado desde las migraciones de Alembic.
-- Uso recomendado: dejar que Render ejecute `flask db upgrade` al desplegar.
-- Ejecuta este archivo solo sobre una base de datos VACÍA:
--   psql "<EXTERNAL_DATABASE_URL>" -f scripts/schema_postgres.sql
-- Incluye alembic_version, por lo que después `flask db upgrade` no repetirá
-- la creación de tablas.
BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 57c995287e51

CREATE TABLE tenants (
    id VARCHAR(36) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    plan VARCHAR(50) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE users (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    email VARCHAR(255) NOT NULL, 
    password_hash VARCHAR(255) NOT NULL, 
    role VARCHAR(11) NOT NULL, 
    is_active BOOLEAN NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_users_email ON users (email);

CREATE INDEX ix_users_tenant_id ON users (tenant_id);

INSERT INTO alembic_version (version_num) VALUES ('57c995287e51') RETURNING alembic_version.version_num;

-- Running upgrade 57c995287e51 -> b4f4e7244171

CREATE TABLE companies (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    name VARCHAR(120) NOT NULL, 
    tax_id VARCHAR(50), 
    industry VARCHAR(80), 
    website VARCHAR(120), 
    phone VARCHAR(30), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_companies_name ON companies (name);

CREATE INDEX ix_companies_tenant_id ON companies (tenant_id);

CREATE TABLE contacts (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    company_id VARCHAR(36), 
    first_name VARCHAR(80) NOT NULL, 
    last_name VARCHAR(80), 
    email VARCHAR(120), 
    phone VARCHAR(30), 
    position VARCHAR(80), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_contacts_company_id ON contacts (company_id);

CREATE INDEX ix_contacts_email ON contacts (email);

CREATE INDEX ix_contacts_tenant_id ON contacts (tenant_id);

CREATE TABLE activity_logs (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    contact_id VARCHAR(36) NOT NULL, 
    user_id VARCHAR(36), 
    type VARCHAR(7) NOT NULL, 
    content TEXT NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE CASCADE, 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
);

CREATE INDEX ix_activity_logs_contact_id ON activity_logs (contact_id);

CREATE INDEX ix_activity_logs_tenant_id ON activity_logs (tenant_id);

CREATE INDEX ix_activity_logs_user_id ON activity_logs (user_id);

UPDATE alembic_version SET version_num='b4f4e7244171' WHERE alembic_version.version_num = '57c995287e51';

-- Running upgrade b4f4e7244171 -> 2003a9b900c1

ALTER TABLE companies ADD COLUMN address VARCHAR(255);

UPDATE alembic_version SET version_num='2003a9b900c1' WHERE alembic_version.version_num = 'b4f4e7244171';

-- Running upgrade 2003a9b900c1 -> f755aad6da27

CREATE TABLE categories (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    color VARCHAR(20) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_categories_tenant_id ON categories (tenant_id);

CREATE TYPE billing_cycle_enum AS ENUM ('monthly', 'yearly', 'quarterly');

CREATE TYPE subscription_status_enum AS ENUM ('active', 'paused', 'cancelled');

CREATE TABLE subscriptions (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    company_id VARCHAR(36), 
    category_id VARCHAR(36), 
    name VARCHAR(120) NOT NULL, 
    cost NUMERIC(10, 2) NOT NULL, 
    billing_cycle billing_cycle_enum NOT NULL, 
    next_billing_date DATE NOT NULL, 
    status subscription_status_enum NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_subscriptions_category_id ON subscriptions (category_id);

CREATE INDEX ix_subscriptions_company_id ON subscriptions (company_id);

CREATE INDEX ix_subscriptions_tenant_id ON subscriptions (tenant_id);

CREATE TYPE transaction_type_enum AS ENUM ('income', 'expense');

CREATE TABLE transactions (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    category_id VARCHAR(36), 
    company_id VARCHAR(36), 
    type transaction_type_enum NOT NULL, 
    amount NUMERIC(10, 2) NOT NULL, 
    description VARCHAR(255) NOT NULL, 
    date DATE NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(category_id) REFERENCES categories (id) ON DELETE SET NULL, 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE SET NULL, 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_transactions_category_id ON transactions (category_id);

CREATE INDEX ix_transactions_company_id ON transactions (company_id);

CREATE INDEX ix_transactions_tenant_id ON transactions (tenant_id);

UPDATE alembic_version SET version_num='f755aad6da27' WHERE alembic_version.version_num = '2003a9b900c1';

-- Running upgrade f755aad6da27 -> c38a2e1f4092

CREATE TABLE stages (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    "order" INTEGER NOT NULL, 
    probability INTEGER NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE
);

CREATE INDEX ix_stages_tenant_id ON stages (tenant_id);

CREATE TYPE deal_status_enum AS ENUM ('open', 'won', 'lost');

CREATE TABLE deals (
    id VARCHAR(36) NOT NULL, 
    tenant_id VARCHAR(36) NOT NULL, 
    company_id VARCHAR(36) NOT NULL, 
    contact_id VARCHAR(36), 
    stage_id VARCHAR(36) NOT NULL, 
    title VARCHAR(120) NOT NULL, 
    value NUMERIC(10, 2) NOT NULL, 
    expected_close_date DATE, 
    status deal_status_enum NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(tenant_id) REFERENCES tenants (id) ON DELETE CASCADE, 
    FOREIGN KEY(company_id) REFERENCES companies (id) ON DELETE CASCADE, 
    FOREIGN KEY(contact_id) REFERENCES contacts (id) ON DELETE SET NULL, 
    FOREIGN KEY(stage_id) REFERENCES stages (id) ON DELETE RESTRICT
);

CREATE INDEX ix_deals_tenant_id ON deals (tenant_id);

CREATE INDEX ix_deals_company_id ON deals (company_id);

CREATE INDEX ix_deals_contact_id ON deals (contact_id);

CREATE INDEX ix_deals_stage_id ON deals (stage_id);

UPDATE alembic_version SET version_num='c38a2e1f4092' WHERE alembic_version.version_num = 'f755aad6da27';

COMMIT;

