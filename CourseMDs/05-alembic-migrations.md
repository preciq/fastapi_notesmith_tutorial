# Chapter 5: Alembic Migrations

Alembic tracks changes to your SQLAlchemy models and generates SQL migration scripts to apply those changes to the database. This chapter covers initializing Alembic with async support, generating migrations, and running them.

## 5.1 Initialize Alembic

From the project root, run:

```bash
alembic init -t async alembic
```

The `-t async` flag uses the **async template**, which configures `env.py` to use SQLAlchemy's async engine. This creates:

```
notesmith/
├── alembic/
│   ├── versions/          # Migration scripts go here
│   ├── env.py             # Migration environment configuration
│   ├── script.py.mako     # Template for new migration files
│   └── README
├── alembic.ini            # Alembic configuration file
└── ...
```

## 5.2 Configure alembic.ini

Open `alembic.ini` and find the `sqlalchemy.url` line. Replace it with an empty value — we will set it dynamically from our application config:

```ini
# alembic.ini
sqlalchemy.url =
```

Leaving it empty here is intentional. The actual URL will come from `env.py` (which reads from our `.env` file), so we do not duplicate the connection string.

## 5.3 Configure env.py

This is the most important file. Open `alembic/env.py` and replace its entire contents with:

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from notesmith.config import settings
from notesmith.database import Base

# Import all models so that Base.metadata contains their table definitions.
# Without these imports, autogenerate will see an empty metadata and generate
# empty migrations.
import notesmith.auth.models  # noqa: F401
import notesmith.notes.models  # noqa: F401

# Alembic Config object (provides access to alembic.ini values)
config = context.config

# Set the database URL from our application settings
config.set_main_option("sqlalchemy.url", settings.database_url)

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# This is what Alembic compares against the database to detect changes
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    Useful for reviewing migration SQL or applying to restricted environments.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

The critical parts:

**Model imports** — Lines like `import notesmith.auth.models` force Python to execute those modules, which registers the model classes with `Base.metadata`. Without these imports, `Base.metadata.tables` would be empty and autogenerate would produce blank migrations.

**`compare_type=True`** — Tells Alembic to detect column type changes (e.g., changing `String(50)` to `String(200)`). Disabled by default.

**`compare_server_default=True`** — Tells Alembic to detect changes to server-side defaults. Disabled by default.

**`pool.NullPool`** — Uses no connection pooling for migrations. Each migration command opens a fresh connection and closes it when done. Migrations are one-off operations, not long-running servers.

**`connection.run_sync(do_run_migrations)`** — Alembic's migration runner is synchronous. This bridges the async connection to the sync migration code.

## 5.4 Generate the Initial Migration

Now generate a migration that creates the `users` and `notes` tables:

```bash
alembic revision --autogenerate -m "Create users and notes tables"
```

Alembic will:

1. Connect to the database
2. Inspect the current schema (empty, since no tables exist)
3. Compare it to `Base.metadata` (which contains the `users` and `notes` tables)
4. Generate a migration script with the differences

You should see output like:

```
INFO  [alembic.autogenerate.compare] Detected added table 'users'
INFO  [alembic.autogenerate.compare] Detected added table 'notes'
  Generating alembic/versions/xxxx_create_users_and_notes_tables.py ... done
```

Open the generated file in `alembic/versions/`. It will look something like:

```python
"""Create users and notes tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-04-01 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('hashed_password', sa.String(length=256), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('email', name=op.f('uq_users_email')),
        sa.UniqueConstraint('username', name=op.f('uq_users_username')),
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('notes',
        # ... similar structure ...
    )


def downgrade() -> None:
    op.drop_table('notes')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
```

**Always review autogenerated migrations before applying them.** Autogenerate is not perfect — it can miss certain changes (like renamed columns, which it sees as a drop + add) and may produce unnecessary operations. Read through `upgrade()` and `downgrade()` to verify they match your intent.

Notice the named constraints (`pk_users`, `uq_users_email`, etc.) — these come from the naming convention we defined in `database.py`. Without naming conventions, PostgreSQL auto-generates names, and Alembic cannot reference them in `downgrade()`.

## 5.5 Apply the Migration

Run:

```bash
alembic upgrade head
```

`head` means "apply all migrations up to the latest." You should see:

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> a1b2c3d4e5f6, Create users and notes tables
```

Verify the tables exist:

```bash
psql -U postgres -d notesmith -c "\dt"
```

You can also verify in DBeaver (recommended).

You should see `users`, `notes`, and `alembic_version` tables. The `alembic_version` table tracks which migration the database is currently at.

## 5.6 The Migration Workflow

Going forward, the workflow for schema changes is:

1. **Modify your SQLAlchemy model** (add a column, change a type, add a table).
2. **Generate a migration**: `alembic revision --autogenerate -m "Description of change"`
3. **Review the generated script** in `alembic/versions/`.
4. **Apply it**: `alembic upgrade head`

Other useful commands:

```bash
# Check current migration version
alembic current

# Show migration history
alembic history --verbose

# Roll back one migration
alembic downgrade -1

# Roll back to the beginning (empty database)
alembic downgrade base

# Generate a migration script without autogenerate (empty template)
alembic revision -m "Manual migration"
```

## 5.7 Handling Common Issues

**"Target database is not up to date"** — Run `alembic upgrade head` before generating new migrations.

**Autogenerate produces an empty migration** — Your model imports in `env.py` are missing or wrong. Verify that `import notesmith.auth.models` and `import notesmith.notes.models` are present and not raising errors.

**"Can't locate revision"** — The `alembic_version` table references a migration that no longer exists in `alembic/versions/`. This usually happens when you delete migration files manually. Fix by setting the version directly: `alembic stamp head` (marks the database as current without running migrations).

**Circular import errors** — If importing models in `env.py` causes circular imports, the issue is in your model files. Use `TYPE_CHECKING` guards (as we did in Chapter 4) to break the cycle.

---

Proceed to [Chapter 6: CRUD Operations and the Service Layer](./06-crud-operations.md).
