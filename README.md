# stillhead

stillhead runs Alembic migrations for a database that several modules share.

Each module owns its tables, its revisions and its version table. Two people can add revisions to
two modules at the same time, and they get no merge conflict.

Each word in this README has one meaning. See [CONTEXT.md](CONTEXT.md).

## Install

```console
$ pip install stillhead
```

Install a database driver too. SQLite needs nothing. Postgres needs `psycopg[binary]`.

stillhead needs Python 3.10 or later.

## Define a module

A module has three parts: its tables, its revisions and its definition.

```python
# myapp/notes/models.py
from sqlalchemy import Column, MetaData, String, Table

metadata = MetaData()

note = Table(
    "notes_note",
    metadata,
    Column("id", String(36), primary_key=True),
)
```

```python
# myapp/notes/migrations.py
from stillhead import define_module, versions_dir

from myapp.notes.models import metadata

NOTES = define_module(
    name="notes",
    metadata=metadata,
    versions_path=versions_dir("myapp.notes"),
)
```

Put the revisions in `myapp/notes/versions/`. Create that directory before the first revision.

The version table of the module is `notes_alembic_version`: the prefix and the suffix
`alembic_version`. To use another suffix, give `version_table_suffix`.

### Rules

A module must obey these rules:

- Start the name of each table with the prefix. The default prefix is the module name and an
  underscore, for example `notes_`.
- Put only the tables of the module in its `MetaData`.
- Do not give the `MetaData` a schema.
- Do not add a foreign key to a table of another module.

A foreign key between two tables of one module is correct. A foreign key to another module is
not: the two modules are then one module. To use data from another module, get it with an event, a
call or a copy.

`validate_module` checks these rules. stillhead validates each module before it migrates it.

## Apply migrations

Call `apply_pending` when your application starts:

```python
from sqlalchemy import create_engine
from stillhead import apply_pending

engine = create_engine("sqlite:///app.db")
apply_pending([NOTES, SYNC], engine)
```

`apply_pending`:

- validates each module, and the modules together;
- applies the pending revisions of each module, up to head;
- does nothing when no revision is pending;
- applies the modules in name order;
- accepts an `Engine` or a URL, and disposes of the engine that it makes from a URL.

`apply_pending` does not read environment variables.

**Only one process can apply migrations at a time.** stillhead does not lock the database. When
several instances of your application can start at the same time, do not use `apply_pending`.
Apply the migrations with the CLI, in a release step.

## Use a schema

This section is for Postgres. SQLite has no schemas.

A module never has a schema. Give the schema when you apply the migrations:

```python
apply_pending([NOTES, SYNC], engine, schema="orders")
```

On a connection that you open yourself, use `use_schema`:

```python
from stillhead import commands, use_schema, validate_module

with engine.connect() as connection, use_schema(connection, "orders"):
    commands.upgrade(validate_module(NOTES), connection)
```

`use_schema` sets the search path to one schema during the block. After the block, it sets the
previous search path again.

- Give one schema. Do not give a list such as `orders, public`: autogenerate then sees the tables
  in `public` and drops them.
- End your transactions inside the block. See [Transactions](#transactions).

For one schema per tenant, apply the migrations once for each schema:

```python
for tenant in tenants:
    apply_pending(MODULES, engine, schema=tenant)
```

Each schema then has its own version tables.

## Use the CLI

The CLI reads the database URL from `STILLHEAD_DATABASE_URL`:

```console
$ export STILLHEAD_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/app
```

`--module` gives the import path of a module definition, as `package.module:ATTRIBUTE`:

```console
$ stillhead status --module myapp.notes.migrations:NOTES --module myapp.sync.migrations:SYNC
notes        db=0002_tags        head=0002_tags        up to date
sync         db=(none)           head=0001_initial     1 pending

$ stillhead upgrade   --module myapp.notes.migrations:NOTES
$ stillhead upgrade   --module myapp.notes.migrations:NOTES --revision 0001_initial
$ stillhead upgrade   --module myapp.notes.migrations:NOTES --sql
$ stillhead current   --module myapp.notes.migrations:NOTES
$ stillhead revision  --module myapp.notes.migrations:NOTES -m "add tags" --autogenerate
$ stillhead downgrade --module myapp.notes.migrations:NOTES --revision base
```

- Each command accepts `--schema`.
- `--sql` prints the SQL. It does not change the database.
- `--autogenerate` compares the models with the database, and writes the difference as a new
  revision.
- The CLI exits with `0` when it succeeds and with `1` when it fails. It writes errors to stderr.
- `status` exits with `0`, also when revisions are pending.

Do not use the `alembic` command. It cannot find the configuration, and it does not filter out the
tables of other modules. Autogenerate then drops those tables.

## Use `commands`

`commands` does what the CLI does, on a connection that you open:

```python
from stillhead import commands, validate_module

notes = validate_module(NOTES)

with engine.connect() as connection:
    commands.pending_revisions(notes, connection)  # ('0002_tags',), newest first
    commands.upgrade(notes, connection)  # to head
    commands.database_revision(notes, connection)  # '0002_tags', or None
    commands.downgrade(notes, connection, "base")

commands.script_head(notes)  # '0002_tags', or None
```

Each function needs a valid module. `validate_module` returns one, with the type
`ValidatedModule`. A type checker refuses a module that is not valid.

### Transactions

stillhead never ends a transaction that it did not start.

- Before you give a connection to `commands` or `use_schema`, commit or roll back. If a transaction
  is open, stillhead raises `OpenTransaction` and changes nothing. This is also true for a
  transaction that only read data. It can hold a `SET` or a lock, and a rollback would lose them.
- The read functions, such as `commands.pending_revisions`, end the transactions that they start.
  They do not end a transaction that was already open.
- End your transactions inside a `use_schema` block. If a transaction is still open when the block
  ends, `use_schema` rolls it back to restore the search path, and raises `OpenTransaction`.
- Do not use a connection in autocommit mode. A failed revision cannot be rolled back on it, so
  stillhead raises `AutocommitConnection`.

```python
with engine.connect() as connection:
    connection.execute(orders.insert(), rows)
    connection.commit()  # without this line, the next call raises OpenTransaction
    commands.upgrade(notes, connection)
```

## Test a module

```python
import pytest
from stillhead import validate_module, validate_module_set
from stillhead.testing import assert_migrations_match_models, empty_namespaces

MODULES = [NOTES, SYNC]


@pytest.mark.parametrize("module", MODULES)
def test_module_is_valid(module):
    validate_module(module)


def test_modules_can_share_a_database():
    validate_module_set(MODULES)


def test_revisions_match_models(engine):
    with empty_namespaces(MODULES, engine):
        for module in validate_module_set(MODULES):
            assert_migrations_match_models(module, engine)
```

- `validate_module` checks the rules of one module. It needs no database.
- `validate_module_set` checks each module. It also checks that no two modules have the same name,
  and that no prefix starts another prefix.
- `empty_namespaces` drops the tables of the modules before the block and after it.
- `assert_migrations_match_models` applies all the revisions, then compares the database with the
  models.

Alembic does not compare row-level security policies, views, functions or triggers. The test
cannot find a difference in them.

## Errors

All errors are in `stillhead.errors`. Each message tells you how to fix the problem. Two errors
need more explanation.

### `DatabaseAheadOfBuild`

The database has a stamp that this build does not have. There are two causes:

- **A newer build migrated the database.** Install that build, or a newer one. Do not change the
  stamp to an older revision: the newer revisions can delete columns that the old build uses.
- **A branch changed a revision that the database already applied.** This usually happens to a
  development database. Make a backup. Then set the stamp to the last revision that the two
  branches share, or delete the database.

```sql
UPDATE notes_alembic_version SET version_num = '0006_last_shared';
```

The error has four attributes: `module`, `stamped`, `head` and `version_table`. `head` is `None`
when the build has no revisions at all, for example when a package lost its `versions/` directory.

### `IrreversibleRevision`

Raise it in `downgrade()` when you cannot undo the revision without losing data.

Do not write a `downgrade()` that does nothing. Alembic then changes the stamp, but not the tables,
and the next upgrade fails.

## SQLite

SQLite does not check foreign keys unless you tell it to, on each connection. stillhead does not
change your engine. Add this listener yourself:

```python
from sqlalchemy import event


@event.listens_for(engine, "connect")
def _check_foreign_keys(dbapi_connection, _record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
```

Use the `connect` event. Inside a transaction, SQLite ignores the pragma.

During a migration, stillhead turns the foreign key checks off, and then sets your value again.
After each revision, it checks the foreign keys of the module. If a row points to a missing row,
it raises `BrokenForeignKeys`, and the stamp stays at the previous revision.

When a revision fails on SQLite, its data changes are rolled back. Its table changes can stay,
because the SQLite driver commits a table change before the transaction starts. Make a backup
before you migrate a SQLite database, and restore it if a revision fails.

## Several services in one database

`validate_module_set` sees only the modules that you give it. It does not see the modules of
another service in the same database.

Give each service its own schema. If services must share a schema, start each prefix with the
service name:

```python
define_module(name="notes", ..., table_prefix="orders_notes_")
```

Then a service name must not be the start of another service name. For example, `auth` with the
module `admin_users`, and `auth_admin` with the module `users`, both make the prefix
`auth_admin_users_`.

## PyInstaller

Add the `versions/` directory of each module to the `datas` of your `.spec` file:

```python
a = Analysis(
    ["boot.py"],
    datas=[("src/myapp/notes/versions", "myapp/notes/versions")],
)
```

The destination must match the import path of the module. stillhead adds its own files with its
PyInstaller hook.
