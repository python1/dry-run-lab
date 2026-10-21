import pytest

from dryrun_lab.cli import main


def test_help_keeps_the_full_disclaimer(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    assert "Not affiliated with or endorsed by Cisco." in text
    assert "Created by Paul Charydczak" in text
    assert "[computed]" not in text
