from dryrun_lab.facts import annotate_warnings, routing_enabled
from dryrun_lab.showfmt import show_running_config, show_unsimulated


def test_routing_follows_the_last_directive() -> None:
    assert routing_enabled("hostname R1\nip routing\n") is True
    assert routing_enabled("hostname SW2\n") is False
    assert routing_enabled("ip routing\nno ip routing\n") is False
    assert routing_enabled("no ip routing\nip routing\n") is True
    assert routing_enabled("! ip routing\n") is False
    assert routing_enabled(" ip routing \n") is True


def test_default_gateway_wording_is_per_device() -> None:
    rows = [
        {
            "device": "R1",
            "text": "ip default-gateway 192.0.2.2",
            "detail": "This feature is not currently supported",
            "kind": "parse",
        },
        {
            "device": "SW1",
            "text": "ip default-gateway 10.99.0.1",
            "detail": "This feature is not currently supported",
            "kind": "parse",
        },
        {
            "device": "SW9",
            "text": "ip default-gateway 10.1.1.1",
            "detail": "This feature is not currently supported",
            "kind": "parse",
        },
    ]
    configs = {
        "R1": "hostname R1\nip routing\n",
        "SW1": "ip routing\n",
        "SW9": "hostname SW9\nno ip routing\n",
    }
    out = annotate_warnings(rows, configs)
    assert out[0]["detail"] == "ignored when ip routing is enabled"
    assert out[0]["kind"] == "ignored"
    assert out[1]["kind"] == "ignored"
    assert all(row.get("device") != "SW9" for row in out)


def test_show_warnings_split_ignored_from_not_simulated() -> None:
    ignored = show_unsimulated(
        "R1",
        [
            {
                "line": 72,
                "text": "ip default-gateway 192.0.2.2",
                "detail": "ignored when ip routing is enabled",
                "kind": "ignored",
            }
        ],
    )
    assert "ignored when ip routing is enabled" in ignored
    assert "NOT simulated" not in ignored
    missed = show_unsimulated(
        "SW2",
        [
            {
                "line": 46,
                "text": "ip default-gateway 10.99.0.1",
                "detail": "This feature is not currently supported",
                "kind": "parse",
            }
        ],
    )
    assert "NOT simulated" in missed
    assert "not currently supported" in missed
    assert "ignored when ip routing is enabled" not in missed


def test_running_config_does_not_call_an_ignored_line_unsimulated() -> None:
    text = show_running_config(
        "hostname R1\n",
        [
            {
                "line": 72,
                "text": "ip default-gateway 192.0.2.2",
                "detail": "ignored when ip routing is enabled",
                "kind": "ignored",
            }
        ],
    )
    assert "No unparsed lines were reported" in text
    assert "ignored when ip routing is enabled" in text
    assert "NOT simulated" not in text
