"""Lot 1 du schéma v3 : métiers, business units et rôles (ADR-0047 du front).

business_lines : métiers de Fondasol, repris des valeurs de projects.code_metier. Les libellés ne
sont pas encore fournis par le métier : label_fr reçoit le code en attendant.

business_units : centres analytiques, repris des codes de l'ancien Solscore (services et
email_services, même nomenclature que le département Azure AD). Le métier n'est rempli que pour
une agence (deux chiffres ou LU, puis le code métier : 31GT, 44EN, LUGT) ; directions et
fonctions support (DTHY, GFIT…) restent sans métier pour l'instant.

users : service_id recevait le département Azure AD brut ; il passe dans department, et
business_unit_code ne garde que les codes connus de business_units.

roles, user_roles : tables créées vides, la liste des rôles reste à décider (ADR-0023).
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

BUSINESS_LINES = ["GT", "MG", "CO", "EN", "HY", "PS", "LB", "RD"]

AGENCY_CODE = "^([0-9]{2}|LU)[A-Z]{2}$"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_lines (
            code text PRIMARY KEY,
            label_fr text NOT NULL,
            label_en text,
            position integer
        )
        """
    )
    values = ", ".join(f"('{code}', '{code}', {position})" for position, code in enumerate(BUSINESS_LINES, start=1))
    op.execute(f"INSERT INTO business_lines (code, label_fr, position) VALUES {values} ON CONFLICT (code) DO NOTHING")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_units (
            code text PRIMARY KEY,
            libelle text NOT NULL,
            business_line text REFERENCES business_lines (code) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO business_units (code, libelle, business_line)
        SELECT codes.code,
               COALESCE(NULLIF(trim(services.libelle), ''), codes.code),
               CASE WHEN codes.code ~ '{AGENCY_CODE}' THEN business_lines.code END
        FROM (
            SELECT id AS code FROM services
            UNION
            SELECT service_code FROM email_services WHERE service_code IS NOT NULL AND trim(service_code) <> ''
        ) AS codes
        LEFT JOIN services ON services.id = codes.code
        LEFT JOIN business_lines ON business_lines.code = right(codes.code, 2)
        ON CONFLICT (code) DO NOTHING
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_business_units_line ON business_units (business_line)")

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS department text")
    op.execute("UPDATE users SET department = service_id")
    op.execute("ALTER TABLE users RENAME COLUMN service_id TO business_unit_code")
    op.execute("UPDATE users SET business_unit_code = NULL WHERE business_unit_code NOT IN (SELECT code FROM business_units)")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_business_unit_code_fkey
            FOREIGN KEY (business_unit_code) REFERENCES business_units (code) ON DELETE SET NULL
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS roles (
            code text PRIMARY KEY,
            libelle text NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            role_code text NOT NULL REFERENCES roles (code) ON DELETE RESTRICT,
            granted_at timestamp(0) with time zone NOT NULL,
            PRIMARY KEY (user_id, role_code)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_roles")
    op.execute("DROP TABLE IF EXISTS roles")
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_business_unit_code_fkey")
    op.execute("ALTER TABLE users RENAME COLUMN business_unit_code TO service_id")
    op.execute("UPDATE users SET service_id = department")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS department")
    op.execute("DROP TABLE IF EXISTS business_units")
    op.execute("DROP TABLE IF EXISTS business_lines")
