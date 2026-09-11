"""Create the schema and the admin user on a fresh database.

Run it from cPanel -> Setup Python App -> "Execute python script", with:

    bootstrap.py

That box runs the script inside the application's virtualenv, which is the
only place the dependencies exist -- so it works even on an account with no
SSH access, where `alembic upgrade head` cannot be typed at all.

Safe to run more than once. Alembic skips revisions that are already applied,
and the seed returns without touching anything when the admin already exists.
Neither step drops or rewrites data.

It reads the same environment the application does, so DATABASE_URL, ADMIN_EMAIL
and ADMIN_PASSWORD must already be set in the cPanel environment variables
before this runs.
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Same reason as in passenger_wsgi.py: cPanel's script runner does not promise
# a working directory, and a .env that is not found leaves this script trying
# to migrate the default localhost database rather than the real one.
os.chdir(HERE)


def _fail(message: str) -> int:
    print("FAILED: " + message)
    return 1


def upgrade_schema() -> None:
    """Apply every Alembic revision to the configured database."""
    from alembic import command
    from alembic.config import Config

    config = Config(os.path.join(HERE, "alembic.ini"))
    # Passenger and the cPanel script runner both start with an unpredictable
    # working directory, and alembic.ini's paths are relative to the CWD. Both
    # are pinned to this file's directory so neither caller has to care.
    config.set_main_option("script_location", os.path.join(HERE, "migrations"))
    config.set_main_option("prepend_sys_path", HERE)
    command.upgrade(config, "head")


def main() -> int:
    print("WRCC backend bootstrap")
    print("=" * 50)

    try:
        from app.config import get_settings

        settings = get_settings()
    except Exception as exc:  # noqa: BLE001 - a config error is the likely one
        # Never `raise`: the traceback would print DATABASE_URL, which carries
        # the database password, into a cPanel panel that stays on screen.
        return _fail(
            "configuration did not load (" + type(exc).__name__ + "). Check the "
            "environment variables in Setup Python App. The message is withheld "
            "because it usually quotes DATABASE_URL."
        )

    # Naming the driver, never the DSN.
    driver = settings.database_url.split("://", 1)[0]
    print("environment: " + settings.app_env)
    print("driver:      " + driver)

    if not settings.admin_email or not settings.admin_password:
        return _fail("ADMIN_EMAIL and ADMIN_PASSWORD are not set.")

    print("\n[1/2] applying migrations...")
    try:
        upgrade_schema()
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
        return _fail("the migrations did not apply. Nothing was seeded.")
    print("      schema is at head.")

    print("\n[2/2] seeding the admin user...")
    try:
        from app.db.seed import seed_admin

        created = asyncio.run(seed_admin())
    except Exception:  # noqa: BLE001
        print(traceback.format_exc())
        return _fail("the admin user could not be seeded.")

    print("      created." if created else "      already existed, left alone.")

    print("\n" + "=" * 50)
    print("Done. Restart the application, then check /api/health/ready —")
    print('it must answer {"status":"ready","database":"up"}.')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
