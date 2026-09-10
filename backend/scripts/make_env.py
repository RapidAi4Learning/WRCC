"""Generate a production .env for the FastComet deployment.

cPanel's environment-variable editor takes one name and one value per click,
which is a poor way to enter twenty-five of them. The application already reads
a `.env` file, so this writes one — you fill in the handful of values only you
have, upload the file to the application root, and skip that screen entirely.

    python -m scripts.make_env --out .env.production

Then open the file, replace every FILL_IN, and upload it as `.env`.

Secrets that can be generated are generated here, freshly, rather than left as
placeholders. That is deliberate: the alternative is copying the old ones
across, and a migration is the cheapest possible moment to rotate them —
afterwards, changing them means reconnecting accounts.

The one it will not generate is TOKEN_ENCRYPTION_KEY. That key decrypts the
stored OAuth tokens, so a new one is only safe on a database that has never
held any, and getting that wrong costs a reconnection of every social account.
It is left as FILL_IN so the choice is made on purpose.

Nothing here reads your existing configuration, and the file it writes is
gitignored.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

FILL = "FILL_IN"

# Long enough that AUTH_SECRET clears the 32-byte minimum config.py enforces in
# production with room to spare.
_SECRET_BYTES = 48


def _secret() -> str:
    return secrets.token_urlsafe(_SECRET_BYTES)


def render(api_base_url: str, frontend_origin: str, *, proxied: bool) -> str:
    """Build the file.

    `proxied` selects between the two deployment shapes:

    * True  — the frontend rewrites /api/* to the backend, so the public API
      origin *is* the frontend's. The OAuth redirect URIs registered with Meta
      and LinkedIn keep working untouched, and only images are fetched from the
      API host directly (which keeps them off the frontend's bandwidth).
    * False — the browser calls the API host directly. Simpler to reason about,
      but the redirect URIs change, so both provider dashboards need updating
      before an account can be connected.
    """
    public_api = frontend_origin if proxied else api_base_url
    media_line = (
        f"PUBLIC_MEDIA_BASE_URL={api_base_url}"
        if proxied
        else "# PUBLIC_MEDIA_BASE_URL=   # unset: falls back to PUBLIC_API_BASE_URL"
    )

    return f"""# WRCC backend — production environment for FastComet.
#
# Upload to the application root as `.env`. Both entry points chdir there
# first, so it is found regardless of how Passenger starts the process.
#
# Replace every {FILL} before uploading. Anything left as {FILL} will either
# fail validation at startup or, worse, be accepted and behave wrongly.

# ── Core ──
APP_ENV=production
LOG_LEVEL=INFO
FRONTEND_ORIGIN={frontend_origin}

# ── Database ──
# The names cPanel gave you, including its account prefix — e.g.
# postgresql+asyncpg://acct_wrccapp:PASSWORD@localhost:5432/acct_wrcc
# `localhost` alone is not a DSN: it passes config validation and then fails on
# the first query, which reads as "the app is broken" rather than "this is
# misconfigured".
DATABASE_URL=postgresql+asyncpg://{FILL}:{FILL}@localhost:5432/{FILL}

# Default is 10, and SQLAlchemy adds an overflow of 10 on top — up to 20
# connections per process, times however many workers Passenger starts, against
# a max_connections you share with other accounts on this server.
DB_POOL_SIZE=3

# ── Auth ──
# Freshly generated. Do not reuse the value from the old deployment.
AUTH_SECRET={_secret()}
SESSION_COOKIE_SAMESITE=lax

# The bootstrap login. Change the password from whatever the old deployment
# used — this is a new database, so it costs nothing to set it right now.
ADMIN_EMAIL={FILL}
ADMIN_PASSWORD={FILL}

# ── Public URLs ──
PUBLIC_API_BASE_URL={public_api}
{media_line}

# ── Secrets ──
# Freshly generated, and deliberately different from AUTH_SECRET: config.py
# refuses to start if they match, because one leaked key must not be able to
# both forge sessions and sign image URLs.
MEDIA_SIGNING_SECRET={_secret()}

# NOT generated, on purpose. This Fernet key decrypts the OAuth tokens in
# social_accounts. On a database that has never held one, a new key is safe:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# If any account has already been connected against an existing key, copy that
# key here instead — a new one makes every stored token undecryptable.
TOKEN_ENCRYPTION_KEY={FILL}

# ── LLM ──
LLM_MOCK=false
LLM_PROVIDER=openai
OPENAI_API_KEY={FILL}
OPENAI_MODEL=gpt-5-mini
IMAGE_MODEL=gpt-image-1

# ── Publishing ──
PUBLISH_MOCK=false

# ── Meta (Facebook + Instagram) ──
META_APP_ID={FILL}
META_APP_SECRET={FILL}
META_GRAPH_VERSION=v23.0
META_LOGIN_CONFIG_ID={FILL}

# ── LinkedIn ──
LINKEDIN_CLIENT_ID={FILL}
LINKEDIN_CLIENT_SECRET={FILL}
LINKEDIN_API_VERSION=202607

# ── Scraper ──
SCRAPER_BASE_URL=https://wrcc.nsw.edu.au
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base-url",
        default="https://api.wrcc.ai4l.com.au",
        help="Public HTTPS origin of the backend on FastComet.",
    )
    parser.add_argument(
        "--frontend-origin",
        default="https://wrcc.social-media-marketing.ai4l.com.au",
        help="Public HTTPS origin of the frontend on Vercel.",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help=(
            "The browser calls the API host directly, instead of the frontend "
            "proxying /api/*. Requires updating the Meta and LinkedIn redirect "
            "URIs before an account can be connected."
        ),
    )
    parser.add_argument("--out", default=".env.production")
    args = parser.parse_args(argv)

    destination = Path(args.out)
    if destination.exists():
        # Overwriting would regenerate AUTH_SECRET and MEDIA_SIGNING_SECRET,
        # quietly invalidating every session issued against the old file.
        print(f"refusing to overwrite {destination} — delete it first")
        return 1

    body = render(
        args.api_base_url, args.frontend_origin, proxied=not args.direct
    )
    destination.write_text(body, encoding="utf-8")

    # Only the settings lines. A plain count over the whole file also picks up
    # the two mentions in the header comment, which would overstate how much
    # work is left by exactly two every time.
    remaining = sum(
        line.count(FILL)
        for line in body.splitlines()
        if not line.lstrip().startswith("#")
    )
    print(f"wrote {destination}")
    print("  AUTH_SECRET and MEDIA_SIGNING_SECRET generated fresh")
    print(f"  {remaining} value(s) still marked {FILL}")
    print(
        "\nmode: "
        + ("frontend proxies /api/*" if not args.direct else "browser calls the API directly")
    )
    print("\nNext: fill it in, upload to the application root as `.env`, restart.")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
