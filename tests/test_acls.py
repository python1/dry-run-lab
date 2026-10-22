from dryrun_lab.acls import numbered_config, parse_acls
from dryrun_lab.configedit import apply_config_lines

OFFICE = """hostname R1
!
ip access-list extended GUEST-IN
 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255
 deny ip 10.30.30.0 0.0.0.255 10.20.20.0 0.0.0.255
 permit ip any any
!
end
"""


def _apply(commands: list[str], config: str = OFFICE) -> str:
    return apply_config_lines(config, commands)


def test_numbered_line_inserts_before_permit_and_keeps_sequences() -> None:
    updated = _apply(
        [
            "ip access-list extended GUEST-IN",
            "25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
            "end",
        ]
    )
    assert " deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255" in updated
    assert " 10 deny" not in updated
    assert " 20 deny" not in updated
    assert " 30 permit" not in updated
    assert " 25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255" in updated
    assert updated.index(" 25 deny") < updated.index(" permit ip any any")
    sequences = [(ace.seq, ace.explicit) for ace in parse_acls(updated)[0].aces]
    assert sequences == [(10, False), (20, False), (25, True), (30, False)]
    rendered = numbered_config(updated)
    assert " 10 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255" in rendered
    assert " 20 deny ip 10.30.30.0 0.0.0.255 10.20.20.0 0.0.0.255" in rendered
    assert rendered.index(" 25 deny") < rendered.index(" 30 permit ip any any")


def test_no_sequence_and_no_full_line_remove_entries() -> None:
    numbered = _apply(
        [
            "ip access-list extended GUEST-IN",
            "25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
            "end",
        ]
    )
    without_seq = _apply(["ip access-list extended GUEST-IN", "no 25", "end"], numbered)
    assert "10.99.0.0" not in without_seq
    assert " deny ip 10.30.30.0 0.0.0.255 10.10.10.0" in without_seq
    assert " 10 deny" not in without_seq
    assert " permit ip any any" in without_seq
    assert " 30 permit" not in without_seq
    assert [ace.seq for ace in parse_acls(without_seq)[0].aces] == [10, 20, 30]
    without_text = _apply(
        [
            "ip access-list extended GUEST-IN",
            "no deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255",
            "end",
        ],
        numbered,
    )
    assert "10.10.10.0" not in without_text
    assert " 20 deny ip 10.30.30.0 0.0.0.255 10.20.20.0 0.0.0.255" in without_text
    assert " 30 permit" not in without_text
    assert [ace.seq for ace in parse_acls(without_text)[0].aces] == [20, 25, 30]


def test_resequence_renumbers_and_a_bad_form_is_kept() -> None:
    updated = _apply(["ip access-list resequence GUEST-IN 100 10", "end"])
    assert "ip access-list resequence" not in updated
    sequences = [(ace.seq, ace.explicit) for ace in parse_acls(updated)[0].aces]
    assert sequences == [(100, True), (110, True), (120, True)]
    assert " 100 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255" in updated
    assert " 120 permit ip any any" in updated
    appended = _apply(
        [
            "ip access-list extended GUEST-IN",
            "deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
            "end",
        ],
        updated,
    )
    assert " 130 deny" not in appended
    assert [ace.seq for ace in parse_acls(appended)[0].aces] == [100, 110, 120, 130]
    kept = _apply(["ip access-list resequence GUEST-IN 0 10", "end"])
    assert "ip access-list resequence GUEST-IN 0 10" in kept
    missing = _apply(["ip access-list resequence OTHER 10 10", "end"])
    assert "ip access-list resequence OTHER 10 10" in missing


def test_snapshot_text_carries_sequence_numbers_without_editing_the_original() -> None:
    rendered = numbered_config(OFFICE)
    assert " 10 deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255" in rendered
    assert " 30 permit ip any any" in rendered
    assert " deny ip 10.30.30.0 0.0.0.255 10.10.10.0 0.0.0.255\n" in OFFICE
