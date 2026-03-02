"""Gunicorn configuration for INTERCEPT."""


def post_fork(server, worker):
    """Apply gevent monkey-patching immediately after fork.

    Gunicorn's built-in gevent worker is supposed to handle this, but on
    some platforms (notably Raspberry Pi / ARM) the worker deadlocks during
    its own init_process() before it gets to patch.  Doing it here — right
    after fork, before any worker initialisation — avoids the race.
    """
    try:
        from gevent import monkey
        monkey.patch_all(subprocess=False)
    except Exception:
        pass


def post_worker_init(worker):
    """Suppress noisy SystemExit tracebacks during gevent worker shutdown.

    When gunicorn receives SIGINT, the gevent worker's handle_quit()
    calls sys.exit(0) inside a greenlet. Gevent treats SystemExit as
    an error by default and prints a traceback. Adding it to NOT_ERROR
    silences this harmless noise.
    """
    try:
        import ssl
        from gevent import get_hub
        hub = get_hub()
        suppress = (SystemExit, ssl.SSLZeroReturnError, ssl.SSLError)
        for exc in suppress:
            if exc not in hub.NOT_ERROR:
                hub.NOT_ERROR = hub.NOT_ERROR + (exc,)
    except Exception:
        pass
