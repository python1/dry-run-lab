"""Reachability labels explain a sample host that is not the address in the ACL."""

from dryrun_lab.examples import load_office_lab
from dryrun_lab.probes import probes_for_acl


def test_acl_probe_says_why_the_sample_host_is_not_the_configured_address() -> None:
    lab = load_office_lab()
    probes = probes_for_acl(
        lab,
        "R1",
        [
            "ip access-list extended GUEST-IN",
            "25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255",
        ],
    )
    assert probes
    label = probes[0].label()
    assert "10.30.30.50 -> 10.99.0.50" in label
    assert "10.99.0.50 is a sample host in 10.99.0.0/24" in label
    assert "10.99.0.1 on R1" in label
    assert "10.30.30.50 is a sample host in 10.30.30.0/24" in label
    assert "not a configured address" in label
    assert "stops on that device" in label
