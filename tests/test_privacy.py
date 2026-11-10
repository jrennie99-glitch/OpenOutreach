"""The process does not phone home, and the mailbox checks certificates."""
import os
import socket
import ssl
from pathlib import Path

import pytest

from openoutreach.config.models import SiteConfig
from openoutreach.privacy import (
    client_context,
    hub_enabled,
    install_env,
    is_clear_opt_out,
    phone_home_host,
    resend_url_allowed,
    restrict_state_files,
    url_is_blocked,
)


def test_telemetry_flags_are_set_and_an_explicit_export_wins(monkeypatch):
    monkeypatch.delenv("OUTSEND_REPLIES", raising=False)
    monkeypatch.delenv("HF_HUB_DISABLE_TELEMETRY", raising=False)
    install_env()
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert os.environ["DO_NOT_TRACK"] == "1"
    assert os.environ["ANONYMIZED_TELEMETRY"] == "false"
    assert os.environ["CREWAI_DISABLE_TELEMETRY"] == "true"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["OTEL_SDK_DISABLED"] == "true"
    assert os.environ["ANTHROPIC_OPEN_TELEMETRY"] == "false"
    assert os.environ["OUTSEND_REPLIES"] == "hold"

    monkeypatch.setenv("OUTSEND_REPLIES", "model")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    install_env()
    assert os.environ["OUTSEND_REPLIES"] == "model"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"


def test_the_hub_is_not_resolved_and_other_hosts_are_not_blocked():
    assert phone_home_host("hub.openoutreach.app") is True
    assert phone_home_host("api.openai.com") is False
    assert phone_home_host("app.bettercontact.rocks") is False
    assert phone_home_host("smtp.gmail.com") is False
    assert phone_home_host("huggingface.co") is False
    assert url_is_blocked("https://huggingface.co/api/telemetry/v1") is True
    assert url_is_blocked("https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/main/model.onnx") is False
    with pytest.raises(OSError, match="hub.openoutreach.app"):
        socket.getaddrinfo("hub.openoutreach.app", 443)


def test_the_hub_client_does_not_call_the_network(monkeypatch):
    import openoutfind.contacts.service as service

    def boom(*_args, **_kwargs):
        raise AssertionError("the contacts store was called")

    monkeypatch.setattr(service.requests, "post", boom)
    monkeypatch.setattr(service.requests, "get", boom)

    assert service.resolve(object()) is None
    assert service.register_operator() is False
    assert service.hub_balance() == {"balance": None, "known": False}
    assert service.token_in_hand(object()) == ""
    service.contribute(object(), ["person@example.com"], "bettercontact")
    service.share_profiles(
        [{"contact_linkedin_profile_url": "https://example.test/in/a"}], "us", {},
    )
    service.share_companies([{"company": "Acme"}], "us", {})
    assert hub_enabled() is False


def test_a_stored_contacts_token_is_not_exported(db):
    config = SiteConfig.load()
    config.contacts_api_token = "hub-token-not-for-export"
    config.product_docs = "A product."
    config.save()

    exported = config.export()

    assert "OPENOUTFIND_CONTACTS_API_TOKEN" not in exported
    assert exported["OPENOUTFIND_PRODUCT_DOCS"] == "A product."


def test_enabling_the_hub_is_what_exports_the_token(db, monkeypatch):
    monkeypatch.setenv("OPENOUTREACH_ENABLE_HUB", "1")
    config = SiteConfig.load()
    config.contacts_api_token = "hub-token"
    config.save()

    assert config.export()["OPENOUTFIND_CONTACTS_API_TOKEN"] == "hub-token"


def test_mailbox_tls_asks_for_a_verified_context():
    import smtplib

    context = client_context(None)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    given = ssl.create_default_context()
    assert client_context(given) is given
    assert smtplib.SMTP.starttls._openoutreach is True


def test_resend_downloads_stay_on_resend():
    assert resend_url_allowed("https://api.resend.com/emails/receiving/em_1")
    assert resend_url_allowed("https://cdn.resend.dev/raw/em_1")
    assert not resend_url_allowed("http://cdn.resend.dev/raw/em_1")
    assert not resend_url_allowed("https://169.254.169.254/latest/meta-data")
    assert not resend_url_allowed("https://evil.example/raw")
    assert not resend_url_allowed("https://cdn.resend.dev.evil.example/raw")
    assert not resend_url_allowed("https://user:pw@cdn.resend.dev/raw")


@pytest.mark.parametrize("body", [
    "stop",
    "STOP!!!",
    "Please unsubscribe.",
    "don't email me",
    "take me off your list",
])
def test_a_one_line_opt_out_is_recognised(body):
    assert is_clear_opt_out(body)


@pytest.mark.parametrize("body", [
    "",
    "stop by the office next week",
    "please don't stop sending the report",
    "sounds good, let's talk",
])
def test_ordinary_replies_are_not_opt_outs(body):
    assert not is_clear_opt_out(body)


def test_the_database_file_is_private(tmp_path: Path):
    state = tmp_path / "state"
    data = state / "data"
    data.mkdir(parents=True)
    database = data / "db.sqlite3"
    database.write_text("sqlite")
    os.chmod(data, 0o755)
    os.chmod(database, 0o644)

    restrict_state_files(state, database)

    assert stat_mode(data) == 0o700
    assert stat_mode(database) == 0o600


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777
