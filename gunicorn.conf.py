"""Gunicorn configuration for INTERCEPT."""


def post_worker_init(worker):
    """Suppress noisy SystemExit tracebacks during gevent worker shutdown.

    When gunicorn receives SIGINT, the gevent worker's handle_quit()
    calls sys.exit(0) inside a greenlet. Gevent treats SystemExit as
    an error by default and prints a traceback. Adding it to NOT_ERROR
    silences this harmless noise.
    """
    try:
        from gevent import get_hub
        hub = get_hub()
        if SystemExit not in hub.NOT_ERROR:
            hub.NOT_ERROR = hub.NOT_ERROR + (SystemExit,)
    except Exception:
        pass
