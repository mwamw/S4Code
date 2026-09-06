"""Product errors shared by in-process and remote entrypoints."""

from contextlib import contextmanager


class S4CodeError(Exception):
    code = "operation_failed"


class InvalidRequestError(S4CodeError, ValueError):
    code = "invalid_request"


class SessionNotFoundError(InvalidRequestError):
    code = "session_not_found"


class BusyError(S4CodeError, RuntimeError):
    code = "busy"


class ClosedError(S4CodeError, RuntimeError):
    code = "closed"


@contextmanager
def product_operation():
    """Keep framework exception classes out of the product contract."""
    try:
        yield
    except S4CodeError:
        raise
    except (ValueError, TypeError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    except Exception as exc:
        raise S4CodeError(str(exc)) from exc
