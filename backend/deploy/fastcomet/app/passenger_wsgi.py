"""Passenger/LSAPI entry point for the WRCC backend on FastComet shared hosting.

The server speaks WSGI and this application is ASGI, so something has to sit
between them. `a2wsgi.ASGIMiddleware` does that: it starts an event loop in a
daemon thread and runs each request on it.

That thread is the whole difficulty of this file. FastComet runs LiteSpeed, and
CloudLinux's Python selector serves the app through LSAPI, which **preloads the
application in a parent process and then forks children to handle requests**.
A forked child inherits the parent's memory but none of its threads. So a
middleware built at import time hands every child an event-loop object that
looks running and that nothing is driving: each request is queued onto it and
waits forever. The observed symptom is not an error but a hang -- LiteSpeed
returns its own "Request Timeout" 500 after ~120s, and the log fills with
"Killing runaway process ... with SIGTERM". Nothing in the app ever reports a
fault, because from the app's point of view nothing failed.

So the bridge is built **once per process, on that process's first request**,
never at import. It is still built once and reused, which is what the database
pool needs: asyncpg connections stay bound to the loop that opened them, and a
fresh loop per request would surface later as intermittent "attached to a
different loop" errors under concurrency.

Importing `app.main` stays at import time on purpose. It is the expensive and
failure-prone step, it is fork-safe (the SQLAlchemy engine in `app/db/base.py`
is created lazily, so no socket is opened before the fork), and doing it here
means a broken deployment answers with the readable page below instead of an
opaque 500.

Configuration comes from the environment. Set it in cPanel -> Setup Python App
-> Environment variables; the server passes those to the process, and
pydantic-settings reads `os.environ` ahead of any `.env` file. Uploading a
`.env` also works, but the cPanel screen keeps the secrets out of the file
tree, so prefer it.

    cPanel -> Setup Python App:
      Python version:  3.12
      Application root:        api            (must equal the subdomain's
                                               document root)
      Application URL:         api.<domain>   (leave the path field empty)
      Application startup file: passenger_wsgi.py
      Application Entry point:  application
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

# The application package sits beside this file, uploaded as `app/`. The server
# starts the process with an unpredictable working directory, so the path is
# derived from this file's own location rather than from the CWD.
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

LOG_PATH = os.path.join(HERE, "startup_error.log")
# Read once at process startup: a health check must not mistake an old worker
# reading newly uploaded files for a worker that actually loaded the release.
try:
    with open(os.path.join(HERE, ".deploy-release"), encoding="utf-8") as handle:
        _release = handle.read().strip()
except FileNotFoundError:
    _release = "manual"


def _failure_page(summary: str, detail: str):
    """A WSGI app that reports why the real one could not start.

    The server's own response to an import error is an opaque 500, and the
    traceback lands in a log the browser cannot reach -- which is the worst
    possible position to debug a first deployment from.

    The traceback is shown only when DEPLOY_DEBUG=1, and it is never on by
    accident: a stack trace names file paths, installed versions and sometimes
    configuration values, and this endpoint is public.
    """

    def application(environ, start_response):
        body = "WRCC backend failed to start.\n\n" + summary + "\n"
        if os.environ.get("DEPLOY_DEBUG") == "1":
            body += "\n" + detail
        else:
            body += (
                "\nThe full traceback was written to startup_error.log in the "
                "application root — open it in cPanel's File Manager.\n"
                "Or set DEPLOY_DEBUG=1 in the environment and restart to read "
                "it here instead.\n"
            )
        encoded = body.encode("utf-8")
        start_response(
            "500 Internal Server Error",
            [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(encoded))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [encoded]

    return application


def _pong(environ, start_response):
    """Answer `/__wsgi_ping` without touching the ASGI bridge at all.

    This exists to tell two indistinguishable failures apart. When a request
    hangs, the cause is either the hosting chain (LiteSpeed, LSAPI, the
    virtualenv, the .htaccess) or this process's own async plumbing, and the
    browser shows the same timeout for both. `/__wsgi_ping` is pure WSGI, so an
    instant "pong" here alongside a hanging /api/health narrows it to the
    plumbing in a single request. The pid is included only under DEPLOY_DEBUG,
    because it is a debugging detail rather than something a public endpoint
    owes anyone.
    """
    body = "pong"
    if os.environ.get("DEPLOY_DEBUG") == "1":
        body += " pid=" + str(os.getpid())
    encoded = body.encode("utf-8")
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
            ("Cache-Control", "no-store"),
        ],
    )
    return [encoded]


# Everything below is inside the guard, including the chdir. The first version
# of this file left that one statement outside, and when startup failed the
# module raised before `application` was ever defined -- so the server returned
# its own opaque 500 and the readable page above never ran. Nothing at import
# time may be allowed to escape.
try:
    # pydantic-settings resolves `env_file=".env"` against the working
    # directory, and the server does not promise one. Without this the uploaded
    # .env is silently not read and the app comes up on default settings.
    os.chdir(HERE)

    from a2wsgi import ASGIMiddleware

    from app.main import app as asgi_app

    _bridge = None
    _bridge_pid = None
    _bridge_lock = threading.Lock()

    def _reset_after_fork() -> None:
        """Drop the parent's bridge, and its lock, in the freshly forked child.

        The pid check in `_get_bridge` would catch the stale bridge on its own.
        The lock is the subtler half: a lock held by another thread at the
        moment of the fork stays locked forever in the child, and the holder
        does not exist there to release it. Replacing it is only safe here,
        where the child has exactly one thread by definition.
        """
        global _bridge, _bridge_pid, _bridge_lock
        _bridge = None
        _bridge_pid = None
        _bridge_lock = threading.Lock()

    if hasattr(os, "register_at_fork"):  # POSIX only; this host is Linux.
        os.register_at_fork(after_in_child=_reset_after_fork)

    def _get_bridge():
        """The ASGI-to-WSGI bridge belonging to *this* process."""
        global _bridge, _bridge_pid
        pid = os.getpid()
        # Fast path, and no lock, once this process has its own bridge — which
        # is every request after the first one it serves.
        if _bridge is not None and _bridge_pid == pid:
            return _bridge
        with _bridge_lock:
            # Re-checked under the lock: two threads can arrive together on a
            # cold worker, and building twice would leak an event-loop thread.
            if _bridge is None or _bridge_pid != pid:
                _bridge = ASGIMiddleware(asgi_app)
                _bridge_pid = pid
        return _bridge

    def application(environ, start_response):
        def with_release(status, headers, exc_info=None):
            return start_response(status, [*headers, ("X-WRCC-Release", _release)], exc_info)

        if environ.get("PATH_INFO") == "/__wsgi_ping":
            return _pong(environ, with_release)
        return _get_bridge()(environ, with_release)

except BaseException as exc:  # noqa: BLE001 - `application` MUST get defined
    # BaseException, not Exception: a SystemExit raised by a misconfigured
    # dependency would otherwise skip this handler and take the opaque-500 path
    # again. There is no failure mode here worth preferring silence to.
    _summary = type(exc).__name__ + ": " + str(exc)
    _detail = traceback.format_exc()

    # Also written to a file, because the page needs DEPLOY_DEBUG to show the
    # traceback and this can be read from cPanel's File Manager either way.
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as handle:
            handle.write(_detail)
    except OSError:
        pass  # An unwritable directory must not replace one error with another.

    application = _failure_page(_summary, _detail)
