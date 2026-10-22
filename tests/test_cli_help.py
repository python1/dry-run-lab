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
    with pytest.raises(SystemExit) as unconfirm_help:
        main(["link", "unconfirm", "--help"])
    assert unconfirm_help.value.code == 0
    assert "link_id" in capsys.readouterr().out


def test_version_flag_prints_the_stamp(capsys: pytest.CaptureFixture[str]) -> None:
    from dryrun_lab.version import version

    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.strip() == f"dryrun-lab {version()}"


def test_unconfirm_of_a_suggested_link_exits_cleanly(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(base: str, method: str, path: str, body: dict | None = None) -> dict:
        assert method == "POST"
        assert path == "/api/links/abc/unconfirm"
        return {"unconfirm": "already"}

    monkeypatch.setattr("dryrun_lab.cli._request", fake_request)
    assert main(["link", "unconfirm", "abc"]) == 0
    assert capsys.readouterr().out.strip() == "abc is already suggested"


def test_unconfirm_of_a_confirmed_link_reports_the_change(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(base: str, method: str, path: str, body: dict | None = None) -> dict:
        return {"unconfirm": "suggested"}

    monkeypatch.setattr("dryrun_lab.cli._request", fake_request)
    assert main(["link", "unconfirm", "abc"]) == 0
    assert capsys.readouterr().out.strip() == "suggested abc"


def test_help_keeps_the_full_disclaimer(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "Not affiliated with or endorsed by Cisco." in text
    assert "Created by Paul Charydczak" in text
    assert "[computed]" not in text
