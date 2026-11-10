"""Privacy guards for this process.

The children phone home on their own: the finder registers the operator and
uploads discovery pages and resolved work emails to ``hub.openoutreach.app``,
and several libraries send telemetry unless told not to at startup. This
module turns that off before either child is imported, and keeps the mailbox
on TLS that checks the server's certificate.

``OPENOUTREACH_ENABLE_HUB=1`` in the environment *before* the process starts
is the only way the contacts store is contacted. Nothing in the wizard sets it.
"""
from __future__ import annotations

import os
import re
import socket
import ssl
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# Read once, at process start, by ``install_runtime_guards``. A flag flipped
# later does not reopen a process that already replaced the hub client.
_HUB_FLAG = "OPENOUTREACH_ENABLE_HUB"

_TRUE = {"1", "true", "yes", "on"}

# Hosts that exist only to receive telemetry or this project's contacts store.
# Hugging Face is not in this set: the embedding model is downloaded from
# there, and that host is blocked only for the telemetry path (below).
_LANGSMITH_HOSTS = frozenset({
    "api.smith.langchain.com",
    "eu.api.smith.langchain.com",
})
_LOGFIRE_HOSTS = frozenset({
    "logfire-api.pydantic.dev",
    "logfire-us.pydantic.dev",
    "logfire-eu.pydantic.dev",
})
_POSTHOG_HOSTS = frozenset({
    "app.posthog.com",
    "us.i.posthog.com",
    "eu.i.posthog.com",
    "us.posthog.com",
    "eu.posthog.com",
})
_CREWAI_HOSTS = frozenset({
    "telemetry.crewai.com",
})
_RESEND_HOSTS = frozenset({
    "api.resend.com",
    "cdn.resend.dev",
})

# A reply whose whole first line is one of these is an opt-out. The model is
# not asked: a page or an email that says "ignore your instructions" must not
# be able to talk the sender out of honouring it.
_OPT_OUT_LINES = frozenset({
    "stop",
    "please stop",
    "stop please",
    "unsubscribe",
    "please unsubscribe",
    "unsubscribe me",
    "unsubscribe please",
    "remove me",
    "please remove me",
    "remove me from your list",
    "take me off",
    "take me off your list",
    "please take me off your list",
    "opt out",
    "opt-out",
    "do not contact me",
    "do not contact me again",
    "do not email me",
    "do not email me again",
    "don't contact me",
    "don't email me",
    "stop emailing me",
    "stop contacting me",
    "please stop emailing me",
    "please stop contacting me",
})

_RESEND_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_GUARDS_INSTALLED = False
_RESEND_OPEN_LOCK = threading.Lock()


def hub_enabled() -> bool:
    """Whether this process was started with the contacts store explicitly on."""
    return os.environ.get(_HUB_FLAG, "").strip().lower() in _TRUE


def install_env() -> None:
    """Turn silent telemetry off, and keep new files private.

    ``setdefault`` throughout: a variable the operator exported is left as
    they set it. Hugging Face reads ``HF_HUB_DISABLE_TELEMETRY`` while its
    constants module is imported, so this has to run before that import.
    """
    # Files this process creates — the SQLite database in particular — are
    # not group-readable. The database holds the API keys and the mailbox
    # password in plaintext; the directory mode is the other half of that.
    os.umask(0o077)
    flags = {
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        "DISABLE_TELEMETRY": "1",
        "DO_NOT_TRACK": "1",
        "ANONYMIZED_TELEMETRY": "false",
        "CREWAI_DISABLE_TELEMETRY": "true",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "OTEL_SDK_DISABLED": "true",
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
        "ANTHROPIC_OPEN_TELEMETRY": "false",
        "ANTHROPIC_OPEN_TELEMETRY_PROPAGATION": "false",
        "SCARF_NO_ANALYTICS": "true",
        "POSTHOG_DISABLED": "1",
        # Replies answer whatever a stranger wrote. Hold them unless the
        # operator opted in; a clear "stop" is still recorded (see the
        # opt-out gate). Cold mail still goes out when they run send/run.
        "OUTSEND_REPLIES": "hold",
    }
    for name, value in flags.items():
        os.environ.setdefault(name, value)


def silence_hub_credentials() -> None:
    """Drop a contacts-store token the environment was carrying.

    The finder mints one from the operator's email when the variable is
    absent, so removing the token is not what stops the upload — replacing
    the client is. Removing it means a stored token is not handed back to
    a child that would otherwise present it.
    """
    if not hub_enabled():
        os.environ.pop("OPENOUTFIND_CONTACTS_API_TOKEN", None)


def restrict_state_files(state_dir: Path, db_path: Path) -> None:
    """Make the state directory and the database readable by this user only.

    A checkout's root is the state directory (it contains ``manage.py``) and
    is not chmodded — that would hide the working tree. ``data/`` and an
    installed ``~/.openoutreach`` are.
    """
    home_state = Path.home() / ".openoutreach"
    try:
        if state_dir.exists() and state_dir.resolve() == home_state.resolve():
            _chmod(state_dir, 0o700)
    except OSError:
        pass
    data = state_dir / "data"
    if data.is_dir():
        _chmod(data, 0o700)
    _chmod_db(db_path)


def install_runtime_guards() -> None:
    """Replace the hub client, require verified TLS, and refuse phone-home DNS.

    Idempotent. Called once Django has loaded every app, so the children's
    models can be imported here.
    """
    global _GUARDS_INSTALLED
    if _GUARDS_INSTALLED:
        return
    _GUARDS_INSTALLED = True
    silence_hub_credentials()
    _disable_hub_client()
    _require_verified_tls()
    _guard_dns()
    _guard_http_clients()
    _guard_resend_downloads()
    _guard_clear_opt_outs()
    _chmod_sqlite_on_connect()


def client_context(context: ssl.SSLContext | None) -> ssl.SSLContext:
    """A certificate-checking client context, or the one the caller supplied."""
    if context is not None:
        return context
    return ssl.create_default_context()


def is_clear_opt_out(body: str) -> bool:
    """True when *body*'s first line is only an opt-out, not a longer note.

    Matching the whole line, not a word inside it, is what keeps "stop by
    the office" from being read as "stop writing".
    """
    return _opt_out_line(body) in _OPT_OUT_LINES


def resend_url_allowed(url: str) -> bool:
    """True for https URLs on Resend's own API and raw-mail host, and nowhere else."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return host in _RESEND_HOSTS


def phone_home_host(host: object) -> bool:
    """True when *host* is a telemetry or contacts-store name this process refuses."""
    if host is None:
        return False
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii")
        except UnicodeDecodeError:
            return False
    name = str(host).strip().lower().rstrip(".")
    if not name or _looks_like_ip(name):
        return False
    if name == "hub.openoutreach.app":
        return not hub_enabled()
    if name in _LANGSMITH_HOSTS:
        return not _flag_on("LANGCHAIN_TRACING_V2") and not _flag_on("LANGSMITH_TRACING")
    if name in _LOGFIRE_HOSTS:
        return not os.environ.get("LOGFIRE_TOKEN", "").strip()
    if name in _POSTHOG_HOSTS or name in _CREWAI_HOSTS:
        return True
    if name == "sentry.io" or name.endswith(".ingest.sentry.io"):
        return not os.environ.get("SENTRY_DSN", "").strip()
    return False


def url_is_blocked(url: str) -> bool:
    """True for a phone-home URL, including Hugging Face's telemetry path only."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if phone_home_host(host):
        return True
    path = parsed.path or ""
    return host in {"huggingface.co", "www.huggingface.co"} and path.startswith("/api/telemetry")


# ── the hub client ───────────────────────────────────────────────


def _disable_hub_client() -> None:
    """Make every contacts-store call return as if the store were down.

    The finder has no off switch. An operator outside the EEA/UK/CH uploads
    every discovery page and every resolved work email, and every install
    with an operator email registers itself, jurisdiction notwithstanding.
    The calls are best-effort, so a no-op is the same shape as an outage
    the finder already handles: resolution misses, and nothing is sent.
    """
    if hub_enabled():
        return
    import openoutfind.contacts.service as service

    def _no_send(*_args, **_kwargs):
        return None

    service.contribute = _no_send
    service.share_profiles = _no_send
    service.share_companies = _no_send
    service.resolve = lambda *_args, **_kwargs: None
    service.register_operator = lambda *_args, **_kwargs: False
    service.token_in_hand = lambda *_args, **_kwargs: ""
    service.hub_balance = lambda *_args, **_kwargs: {"balance": None, "known": False}
    service._send = _no_send
    service._mint = lambda *_args, **_kwargs: ""
    service._register_this_install = lambda *_args, **_kwargs: ""


# ── TLS ──────────────────────────────────────────────────────────


def _require_verified_tls() -> None:
    """Give stdlib SMTP and IMAP a certificate-checking context.

    ``SMTP.starttls()`` and ``IMAP4_SSL()`` with no context use
    ``ssl._create_stdlib_context()``, which does not verify the server.
    The sender's login check passes its own context; the send itself, and
    the Sent-folder read, do not. The app password would then cross a
    connection that accepts any certificate.
    """
    import imaplib
    import smtplib

    if not getattr(smtplib.SMTP.starttls, "_openoutreach", False):
        original_starttls = smtplib.SMTP.starttls

        def starttls(self, *, context=None):
            return original_starttls(self, context=client_context(context))

        starttls._openoutreach = True
        smtplib.SMTP.starttls = starttls

    if not getattr(smtplib.SMTP_SSL.__init__, "_openoutreach", False):
        original_ssl = smtplib.SMTP_SSL.__init__

        def smtp_ssl_init(self, host="", port=0, local_hostname=None, *,
                          timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                          source_address=None, context=None):
            return original_ssl(
                self, host, port, local_hostname,
                timeout=timeout, source_address=source_address,
                context=client_context(context),
            )

        smtp_ssl_init._openoutreach = True
        smtplib.SMTP_SSL.__init__ = smtp_ssl_init

    if not getattr(imaplib.IMAP4_SSL.__init__, "_openoutreach", False):
        original_imap = imaplib.IMAP4_SSL.__init__

        def imap_init(self, host="", port=imaplib.IMAP4_SSL_PORT, *,
                      ssl_context=None, timeout=None):
            return original_imap(
                self, host, port, ssl_context=client_context(ssl_context), timeout=timeout,
            )

        imap_init._openoutreach = True
        imaplib.IMAP4_SSL.__init__ = imap_init


# ── name resolution and HTTP ─────────────────────────────────────


def _guard_dns() -> None:
    if getattr(socket.getaddrinfo, "_openoutreach", False):
        return
    original = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if phone_home_host(host):
            raise OSError(f"blocked phone-home to {host}")
        return original(host, port, *args, **kwargs)

    getaddrinfo._openoutreach = True
    socket.getaddrinfo = getaddrinfo


def _guard_http_clients() -> None:
    """Refuse the telemetry path even when the host itself is allowed.

    Model weights come from ``huggingface.co``. The telemetry endpoint is
    a path on that same host, so DNS cannot tell them apart.
    """
    import requests
    import urllib.request

    if not getattr(requests.sessions.Session.request, "_openoutreach", False):
        original_request = requests.sessions.Session.request

        def request(self, method, url, *args, **kwargs):
            if url_is_blocked(str(url)):
                raise requests.exceptions.ConnectionError(f"blocked phone-home to {url}")
            return original_request(self, method, url, *args, **kwargs)

        request._openoutreach = True
        requests.sessions.Session.request = request

    if not getattr(urllib.request.urlopen, "_openoutreach", False):
        original_open = urllib.request.urlopen

        def urlopen(req, *args, **kwargs):
            target = req.full_url if isinstance(req, urllib.request.Request) else str(req)
            if url_is_blocked(target):
                raise OSError(f"blocked phone-home to {target}")
            return original_open(req, *args, **kwargs)

        urlopen._openoutreach = True
        urllib.request.urlopen = urlopen

    try:
        import httpx
    except ImportError:
        return
    _guard_httpx(httpx.Client, "send")
    _guard_httpx(httpx.AsyncClient, "send")


def _guard_httpx(cls, name: str) -> None:
    original = getattr(cls, name)
    if getattr(original, "_openoutreach", False):
        return

    def send(self, request, *args, **kwargs):
        if url_is_blocked(str(request.url)):
            import httpx
            raise httpx.ConnectError(f"blocked phone-home to {request.url}")
        return original(self, request, *args, **kwargs)

    send._openoutreach = True
    setattr(cls, name, send)


def _guard_resend_downloads() -> None:
    """Fetch a received message's raw bytes only from Resend's own hosts.

    The API response names a download URL. Following it without looking
    would let that URL point at a link-local address or an internal name.
    """
    import urllib.request

    import openoutsend.emails.resend as resend

    if getattr(resend.received_raw, "_openoutreach", False):
        return
    original = resend.received_raw

    def received_raw(api_key: str, email_id: str):
        if not _RESEND_ID.fullmatch(str(email_id)):
            raise OSError("refusing a Resend message id that is not a plain token")

        def open_resend(req, *args, **kwargs):
            target = req.full_url if isinstance(req, urllib.request.Request) else str(req)
            if not resend_url_allowed(target):
                raise OSError(f"refusing URL outside Resend: {target}")
            opener = urllib.request.build_opener(_ResendRedirect)
            return opener.open(req, timeout=kwargs.get("timeout"))

        with _RESEND_OPEN_LOCK:
            saved = urllib.request.urlopen
            urllib.request.urlopen = open_resend
            try:
                return original(api_key, email_id)
            finally:
                urllib.request.urlopen = saved

    received_raw._openoutreach = True
    resend.received_raw = received_raw


class _ResendRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not resend_url_allowed(newurl):
            raise OSError(f"refusing redirect outside Resend: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ── opt-out, before the model ────────────────────────────────────


def _guard_clear_opt_outs() -> None:
    import openoutsend.emails.steps.reply as reply_mod
    import openoutsend.send_pass as send_pass

    if not getattr(send_pass._answer_replies, "_openoutreach", False):
        original_answers = send_pass._answer_replies

        def _answer_replies(result, agent_draft=send_pass.OFF):
            _suppress_clear_opt_outs()
            return original_answers(result, agent_draft)

        _answer_replies._openoutreach = True
        send_pass._answer_replies = _answer_replies

    if not getattr(reply_mod.answer_reply, "_openoutreach", False):
        original_reply = reply_mod.answer_reply

        def answer_reply(deal):
            if is_clear_opt_out(_latest_inbound_body(deal)):
                return reply_mod.honour_opt_out(deal)
            return original_reply(deal)

        answer_reply._openoutreach = True
        reply_mod.answer_reply = answer_reply

    if not getattr(reply_mod.send_drafted_reply, "_openoutreach", False):
        original_draft = reply_mod.send_drafted_reply

        def send_drafted_reply(deal, body: str):
            if is_clear_opt_out(_latest_inbound_body(deal)):
                return reply_mod.honour_opt_out(deal)
            return original_draft(deal, body)

        send_drafted_reply._openoutreach = True
        reply_mod.send_drafted_reply = send_drafted_reply


def _suppress_clear_opt_outs() -> None:
    from openoutsend.leads.suppression import suppress_email
    from openoutsend.planner import unanswered_replies

    for deal in list(unanswered_replies()):
        if is_clear_opt_out(_latest_inbound_body(deal)):
            suppress_email(
                deal.lead.email,
                reason="clear opt-out in the reply, honoured before the model",
            )


def _latest_inbound_body(deal) -> str:
    from openoutsend.emails.models import Direction, Message

    thread_id = getattr(deal, "thread_id", None)
    if not thread_id:
        return ""
    message = (
        Message.objects.filter(thread_id=thread_id, direction=Direction.INBOUND)
        .order_by("-sent_at", "-pk")
        .first()
    )
    return message.body_text if message is not None else ""


def _opt_out_line(body: str) -> str:
    text = (body or "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip().lower().replace("\u2019", "'")
    line = re.sub(r"[^\w\s'-]", "", line)
    line = re.sub(r"\s+", " ", line).strip()
    if len(line) > 80:
        return ""
    return line


# ── files ────────────────────────────────────────────────────────


def _chmod_sqlite_on_connect() -> None:
    from django.db.backends.signals import connection_created

    def _on_connect(sender, connection, **kwargs):
        if connection.vendor != "sqlite":
            return
        name = connection.settings_dict.get("NAME") or ""
        if name and name != ":memory:":
            _chmod_db(Path(name))

    connection_created.connect(_on_connect, dispatch_uid="openoutreach.privacy.sqlite-mode")


def _chmod_db(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if candidate.is_file():
            _chmod(candidate, 0o600)
    parent = path.parent
    home_state = Path.home() / ".openoutreach"
    data_name = parent.name == "data"
    try:
        under_home = parent.resolve() == home_state.resolve() or home_state.resolve() in parent.resolve().parents
    except OSError:
        under_home = False
    if parent.is_dir() and (data_name or under_home):
        _chmod(parent, 0o700)


def _chmod(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError:
        pass


def _flag_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUE


def _looks_like_ip(host: str) -> bool:
    return ":" in host or all(part.isdigit() for part in host.split("."))
