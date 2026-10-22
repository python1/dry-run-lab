---
name: getting-started
description: Start Dry Run Lab on this computer before any other lab command. Use on every lab request, after a restart, and after an Update Bot's Computer wipe.
---

# Dry Run Lab

Created by Paul Charydczak.

## Where the repo comes from

Dry Run Lab is a local project. It is not a published package, and it does not download device software.

The checkout is the directory that contains `ensure-running`, `bin/dryrun-lab`, and `examples/office-lab`. If that directory is already on this computer, use it. Do not look for the project on a device vendor site. The branch is `main`.

When you can clone it:

```bash
git clone https://github.com/python1/dry-run-lab.git
cd dry-run-lab
```

When you cannot clone, download a source archive of `main` and unpack it. On GitHub that is Code, then Download ZIP, or:

```bash
curl -L -o dry-run-lab-main.tar.gz https://github.com/python1/dry-run-lab/archive/refs/heads/main.tar.gz
tar -xzf dry-run-lab-main.tar.gz
cd dry-run-lab-main
```

A release may also offer that same source archive. The archive contains the example configs and the built page. It does not contain a virtualenv or the analysis engine. The starter fetches the engine and creates the virtualenv.

A source archive is stamped with the commit. `bin/dryrun-lab --version` prints it. The same stamp is the first line of `ensure.log` and the page footer. A folder of loose files, with no `.git` directory and no stamp, prints `dryrun-lab unknown`.

## Start it first

`./ensure-running` uses `sudo` and `apt` to install OpenJDK 21 (`openjdk-21-jre-headless`) system-wide when `java` is missing or older than 21. It also installs `curl`, `python3-venv`, and `ca-certificates` when those are missing. It downloads the Batfish jar, question templates, and the matching client wheel, and creates a virtualenv. If Java does not open port 9996, it installs `docker.io` and starts the official image. Nothing is uploaded.

On every use, before any other lab command, run this from the repository root:

```bash
./ensure-running
```

Do that even if it was already run earlier in the same conversation.

Run it again after a computer restart. Run it again after an Update Bot's Computer wipe. Nothing else starts the lab when the machine comes back.

The command is idempotent. It does not use systemd. When the analysis engine is up and a lab is saved, it reloads that lab and recomputes if this process has not computed it yet.

It does not open a browser unless you pass `--open`. Do not pass `--open` unless someone asked to see the page. The browser path reuses an existing Dry Run Lab window, or starts one with a dedicated profile and first-run checks disabled. It never accepts terms or clicks a dialog.

`DRYRUN_HOME` overrides the data directory for that command. `./ensure-running` records the directory it used in `.dryrun-home` in the checkout and in `~/.config/dryrun-lab/install-path` (or under `$XDG_CONFIG_HOME`). Later commands find that install without `DRYRUN_HOME`. If nothing was recorded, the directory is `$HOME/.local/share/dryrun-lab`.

A virtualenv there is reused when it matches the pinned requirements and the same Python interpreter. Those runs do not contact the package index. If that Python is missing or has changed, `./ensure-running` creates the virtualenv again. A home-folder virtualenv can survive a wipe while the interpreter it points at does not.

## Load the example

From the repository root, after `./ensure-running`:

```bash
bin/dryrun-lab load examples/office-lab
```

That reads the synthetic office-lab configs on this machine and posts them to the lab on `127.0.0.1`. The load command prints the full limit once. Configs stay on this machine. Do not open a session to a real device.

## CLI syntax

`bin/dryrun-lab` only talks to `127.0.0.1` or `localhost`. Show, ping, and traceroute transcripts are tagged `[computed]`. Config-mode lines are not. Unknown commands and pipes exit non-zero.

```bash
bin/dryrun-lab status
bin/dryrun-lab devices
bin/dryrun-lab links
bin/dryrun-lab confirm LINK_ID
bin/dryrun-lab dismiss LINK_ID
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
bin/dryrun-lab host add PC40 --ip 10.40.40.50/24 --gw 10.40.40.1
bin/dryrun-lab host list
bin/dryrun-lab host delete PC40
bin/dryrun-lab link add PC40 Ethernet0 SW2 Gi0/12
bin/dryrun-lab link list
bin/dryrun-lab link unconfirm LINK_ID
bin/dryrun-lab link delete LINK_ID
```

`configure terminal` edits that device. The prompt is `R1(config)#`, and `R1(config-if)#`, `R1(config-ext-nacl)#`, `R1(config-vlan)#`, or `R1(config-router)#` in those sub-modes. The banner says `End with CNTL/Z.` `end` recomputes and prints the diff of routes, warnings, and reachability, tagged `[computed]`. `abort` discards the lines. `revert` undoes one edit on that device and recomputes. Call it again for the edit before that. The transcript says `Reverted one edit. Recomputed.` A further `revert` says `Nothing to revert on this device.`

`status` reports the engine, the lab name, and the device and link counts. An inbound ACL needs `ping` with `source` and `ingress`. The reachability diff may name a sample host such as `10.99.0.50` instead of a configured address such as `10.99.0.1`, and the line says why: a trace to the configured address stops on that device.

To verify a revert, save `show running-config` and the ping before the edit, revert, run the same commands, and diff them.

```bash
bin/dryrun-lab status
bin/dryrun-lab show R1 "show running-config" > /tmp/r1-before.txt
bin/dryrun-lab show R1 $'configure terminal\nip access-list extended GUEST-IN\n25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255\nend'
bin/dryrun-lab show R1 "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30"
bin/dryrun-lab show R1 $'configure terminal\nip access-list extended GUEST-IN\n26 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255\nabort'
bin/dryrun-lab show R1 revert
bin/dryrun-lab show R1 "show running-config" > /tmp/r1-after.txt
diff -u /tmp/r1-before.txt /tmp/r1-after.txt
bin/dryrun-lab show R1 $'configure terminal\ninterface GigabitEthernet0/0\n shutdown\nend'
bin/dryrun-lab show R1 revert
```

The same commands work in the page's device CLI. Interface lists sort in natural port order: Gi1/0/2 before Gi1/0/10. `show access-lists` prints sequence numbers. An ACL line without a number is appended. A line that starts with a number is inserted there. `show running-config` leaves a line unnumbered unless you typed the number, resequence wrote it, or omitting it would change the sequence.

A host is an end device with an interface address and `ip default-gateway`. `host add` creates one. `link add` draws a confirmed cable and places the host under the device that cable attaches to. Suggested trunks, access ports, and host cables are not layer-1 edges. Confirm them with `confirm LINK_ID` after `links`. A shared `/30` or `/31` with exactly two physical interfaces is written while it is still suggested, which is why the office OSPF traceroute works before that cable is confirmed. Confirming another cable does not remove it. `link unconfirm LINK_ID` withdraws that edge after the cable has been confirmed. While it is still only suggested, unconfirm leaves the edge and `dismiss LINK_ID` removes the suggestion. If no other layer-1 edge remains, the empty file hubs physical interfaces and that subnet can look connected again. A drawn cable stays listed. An inferred cable comes back as a suggestion. If it is already suggested, unconfirm says so and exits cleanly. A host ping needs every cable on its path confirmed, including the cables `link add` created and the office trunks you confirm. While the layer-1 file is empty, the engine hubs physical interfaces together, so some shared subnets look adjacent even though no cable was confirmed. A ping that starts and ends on addresses of the same device does not use a cable. `ping` and `traceroute` print one sentence under the disposition, and a drop names the ACL sequence. A trace that starts on a host also prints the layer-2 path across those confirmed links. Switches named there are not hops in the computed trace.

## VLAN 40 host path

The office example has no VLAN 40, no R1 Gi0/0.40, and no SW2 Gi0/12. Confirm the R1–SW1, SW1–SW2, and SW1–SW3 cables before the host ping. SRV20 uses the existing VLAN 20 port SW3 Gi0/10. VLAN 40 must be allowed on SW1–SW2 and on SW1–R1.

```bash
bin/dryrun-lab show R1 $'configure terminal\ninterface GigabitEthernet0/0.40\n encapsulation dot1Q 40\n ip address 10.40.40.1 255.255.255.0\n no shutdown\nend'
bin/dryrun-lab show SW1 $'configure terminal\nvlan 40\n name LAB\ninterface GigabitEthernet1/0/1\n switchport trunk allowed vlan add 40\ninterface GigabitEthernet1/0/2\n switchport trunk allowed vlan add 40\nend'
bin/dryrun-lab show SW2 $'configure terminal\nvlan 40\n name LAB\ninterface GigabitEthernet0/1\n switchport trunk allowed vlan add 40\ninterface GigabitEthernet0/12\n switchport mode access\n switchport access vlan 40\n no shutdown\nend'
bin/dryrun-lab host add PC40 --ip 10.40.40.50/24 --gw 10.40.40.1
bin/dryrun-lab host add SRV20 --ip 10.20.20.50/24 --gw 10.20.20.1
bin/dryrun-lab link add PC40 Ethernet0 SW2 Gi0/12
bin/dryrun-lab link add SRV20 Ethernet0 SW3 Gi0/10
bin/dryrun-lab show PC40 "ping 10.20.20.50"
```

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.
