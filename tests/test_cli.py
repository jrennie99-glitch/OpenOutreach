"""What the entry point decides before either child is asked anything."""
import pytest

from cybrreach import __main__ as cli


def test_the_db_flag_comes_off_before_django_sees_it():
    assert cli.extract_db_path(["cybrreach", "find", "10", "--db", "/tmp/x"]) == (
        ["cybrreach", "find", "10"], "/tmp/x")
    assert cli.extract_db_path(["cybrreach", "--db=/tmp/x", "status"]) == (
        ["cybrreach", "status"], "/tmp/x")
    assert cli.extract_db_path(["cybrreach", "status"]) == (["cybrreach", "status"], None)


def test_only_an_explicit_help_asks_for_the_overview():
    assert cli.wants_the_overview(["cybrreach", "-h"])
    assert cli.wants_the_overview(["cybrreach", "help"])
    assert not cli.wants_the_overview(["cybrreach"])
    assert not cli.wants_the_overview(["cybrreach", "help", "find"])


def test_a_bare_invocation_is_run(db, monkeypatch):
    """The whole first-run command is `cybrreach`, with no verb to learn first."""
    asked = []
    monkeypatch.setattr(cli, "_run", lambda rest: asked.append(rest) or 0)

    with pytest.raises(SystemExit) as exit:
        cli.main(["cybrreach"])

    assert exit.value.code == 0
    assert asked == [[]]


def test_send_reaches_the_sender_with_its_own_arguments(monkeypatch):
    """The sender has no management commands, so this is a call and not a call_command."""
    passed = []
    monkeypatch.setattr("openoutsend.__main__.main", lambda argv: passed.append(argv) or 0)

    assert cli._send(["5", "--prompt-line", "opener"]) == 0
    assert passed == [["send", "5", "--prompt-line", "opener"]]


def test_send_passes_a_sequence_through_untouched(monkeypatch):
    """`--sequence DIR` is the sender's; no setting of this host stands in for it."""
    passed = []
    monkeypatch.setattr("openoutsend.__main__.main", lambda argv: passed.append(argv) or 0)

    assert cli._send(["--sequence", "sequences/sample-to-order"]) == 0
    assert passed == [["send", "--sequence", "sequences/sample-to-order"]]


def test_runs_goal_defaults_to_something_small():
    assert cli._goal([]) == cli.DEFAULT_GOAL
    assert cli._goal(["12"]) == 12


@pytest.mark.parametrize("rest", [["nine"], ["0"], ["5", "emails"]])
def test_a_goal_that_cannot_be_read_is_an_error_not_a_default(rest):
    with pytest.raises(SystemExit):
        cli._goal(rest)
