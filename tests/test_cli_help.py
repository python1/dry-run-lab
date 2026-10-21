import pytest

from dryrun_lab.cli import main


def test_host_and_link_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as host_help:
        main(["host", "add", "--help"])
    assert host_help.value.code == 0
    host = capsys.readouterr().out
    assert "--ip" in host and "--gw" in host
    with pytest.raises(SystemExit) as link_help:
        main(["link", "add", "--help"])
    assert link_help.value.code == 0
    link = capsys.readouterr().out
    assert "a_interface" in link and "b_interface" in link


def test_help_keeps_the_full_disclaimer(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "Not affiliated with or endorsed by Cisco." in text
    assert "Created by Paul Charydczak" in text
    assert "[computed]" not in text
