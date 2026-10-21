---
name: getting-started
description: Start Dry Run Lab on this computer before any other lab command. Use on every lab request, after a restart, and after an Update Bot's Computer wipe.
---

# Dry Run Lab

Created by Paul Charydczak.

## Where the repo comes from

Dry Run Lab is a local project. It is not a published package, and it does not download device software.

The checkout is the directory that contains `ensure-running`, `bin/dryrun-lab`, and `examples/office-lab`. If that directory is already on this computer, use it. Do not look for the project on a device vendor site.

If it is not on the computer, unpack a Dry Run Lab source archive into an empty directory and `cd` there. The archive is a `git archive` of branch `stage-1` with the prefix `dryrun-lab/`. It contains the example configs and the built page. It does not contain a virtualenv or the analysis engine. `./ensure-running` fetches the engine and creates the virtualenv.

## Start it first

On every use, before any other lab command, run this from the repository root:

```bash
./ensure-running
```

Do that even if it was already run earlier in the same conversation.

Run it again after a computer restart. Run it again after an Update Bot's Computer wipe. Nothing else starts the lab when the machine comes back.

The command is idempotent. It does not use systemd. When the analysis engine is up and a lab is saved, it reloads that lab and recomputes if this process has not computed it yet.

It does not open a browser unless you pass `--open`. Do not pass `--open` unless someone asked to see the page. The browser path reuses an existing Dry Run Lab window, or starts one with a dedicated profile and first-run checks disabled. It never accepts terms or clicks a dialog.

A virtualenv under `$HOME/.local/share/dryrun-lab` is reused when it matches the pinned requirements and the same Python interpreter. Those runs do not contact the package index. If that Python is missing or has changed, `./ensure-running` creates the virtualenv again. A home-folder virtualenv can survive a wipe while the interpreter it points at does not.

## Load the example

From the repository root, after `./ensure-running`:

```bash
bin/dryrun-lab load examples/office-lab
```

That reads the synthetic office-lab configs on this machine and posts them to the lab on `127.0.0.1`. The load command prints the full limit once. Configs stay on this machine. Do not open a session to a real device.

## CLI syntax

`bin/dryrun-lab` only talks to `127.0.0.1` or `localhost`. Show, ping, and traceroute transcripts are tagged `[computed]`.

```bash
bin/dryrun-lab status
bin/dryrun-lab devices
bin/dryrun-lab links
bin/dryrun-lab warnings
bin/dryrun-lab show R1 "show running-config"
bin/dryrun-lab show R1 "show ip interface brief"
bin/dryrun-lab show R1 "show ip route"
bin/dryrun-lab show SW1 "show vlan brief"
bin/dryrun-lab show SW1 "show interfaces trunk"
bin/dryrun-lab show R1 "show access-lists"
bin/dryrun-lab show R1 "ping 10.10.10.1"
bin/dryrun-lab show R1 "ping 10.20.20.1 source 10.10.10.50 ingress GigabitEthernet0/0.10"
bin/dryrun-lab show R1 "traceroute 10.255.1.1 source 10.50.0.1"
```

`configure terminal` edits that device. `end` recomputes and prints the diff of routes, warnings, and reachability. `abort` discards the lines. `revert` restores the previous config and recomputes.

```bash
bin/dryrun-lab show R1 $'configure terminal\ninterface GigabitEthernet0/0\n shutdown\nend'
bin/dryrun-lab show R1 revert
```

The same commands work in the page's device CLI. Interface lists sort in natural port order: Gi1/0/2 before Gi1/0/10.

A host is an end device with an interface address and `ip default-gateway`. Only a cable confirmed on the canvas is written into the layer-1 topology. Suggested cables are not used. `ping` and `traceroute` print one sentence under the disposition. A trace that starts on a host also prints the layer-2 path across those confirmed links. Switches named there are not hops in the computed trace.

```bash
bin/dryrun-lab show PC40 "ping 10.20.20.50"
```

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.
