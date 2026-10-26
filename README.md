# Dry Run Lab

Created by Paul Charydczak.

Dry Run Lab is a local simulator for a small vendor-style network. You draw routers and switches, paste a config on each device, and confirm the cables the lab inferred. Show commands are computed on this machine by [Batfish](https://github.com/batfish/batfish). Nothing is uploaded, and the lab never opens a session to a real device.

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.

## Supported commands

The device CLI computes these:

- `show running-config`
- `show ip interface brief`
- `show ip route`
- `show vlan brief`
- `show interfaces trunk`
- `show access-lists`
- `show ip ospf neighbor`
- `show warnings`
- `ping` and `traceroute`
- `configure terminal` … `end`, and `abort`
- `revert`

`revert` undoes one `configure terminal` … `end` block on that device and recomputes. Run it again to undo the block before that.

`show ip ospf neighbor` is computed from OSPF sessions. The transcript says it is computed. Priority and dead time are not part of that session.

A `show` command this lab does not compute, such as `show version` or `show spanning-tree`, answers `% Not simulated in this version.` A command that is not a command answers `% Invalid input detected at '^' marker.` Pipes are refused.

## Cables on the page

Click a port dot, then click the port dot on the other device. That draws the cable. Dragging a card moves the device. The port dot is the click target.

Confirming or rejecting a suggested cable recomputes and prints the same routes, warnings, and reachability summary as a config edit. The first line says `Confirmed` or `Rejected`.

## Get the code

The checkout is the directory that contains `ensure-running`, `bin/dryrun-lab`, and `examples/office-lab`.

When you can clone the repository:

```bash
git clone https://github.com/python1/dry-run-lab.git
cd dry-run-lab
```

The branch is `main`.

When you cannot clone, download a source archive of `main` and unpack it. On GitHub that is Code, then Download ZIP, or the branch tarball:

```bash
curl -L -o dry-run-lab-main.tar.gz https://github.com/python1/dry-run-lab/archive/refs/heads/main.tar.gz
tar -xzf dry-run-lab-main.tar.gz
cd dry-run-lab-main
```

The same kind of archive is attached to a release when one is published (Source code zip or tar.gz). The archive contains the example configs and the built page. It does not contain a virtualenv or the analysis engine.

A GitHub source archive is produced by `git archive`, which stamps the commit into the tree. A folder of loose files, copied one by one, has no `.git` directory and no stamp.

## Run it

`./ensure-running` uses `sudo` and `apt` to install packages system-wide when they are missing:

- OpenJDK 21 (`openjdk-21-jre-headless`), if `java` is missing or older than 21
- `curl`, if it is missing
- `python3-venv`, if `ensurepip` is missing
- `ca-certificates`, if the system bundle is missing

It then downloads the Batfish jar, question templates, and the matching pybatfish wheel from one pinned Docker Hub image layer, creates a virtualenv, and installs those into it. The analysis engine is Java. If Java does not open port 9996, the script stops, prints the reason, and points at the log. It does not install or start Docker. Nothing is uploaded. It does not use systemd.

Docker is an untested option, off unless you ask for it:

```bash
./ensure-running --engine docker
```

From a clean Debian or Ubuntu box, with `sudo` and outbound HTTPS:

```bash
./ensure-running
```

The script is idempotent. It installs a JDK 21 if `java` is missing or older, downloads the official Batfish all-in-one jar, creates a virtualenv, and starts the lab in the background. It does not use systemd. When it finishes it prints:

```text
http://127.0.0.1:8742
```

Open that URL on the same machine. The server listens on `127.0.0.1` only. The page fills the browser window. `./ensure-running` does not open a browser. Pass `--open` when you want one:

```bash
./ensure-running --open
```

`bin/open-lab` is what `--open` runs. It reuses a window that is already showing Dry Run Lab. Otherwise it starts the browser with its own profile, `--no-first-run`, and `--no-default-browser-check`. It does not accept terms or click through dialogs.

Run `./ensure-running` again after a computer restart, and after an Update Bot's Computer wipe. If the engine is already up and a saved lab has not been computed in this process, the script reloads that lab and recomputes. You do not have to load the lab by hand before show commands work.

`bin/start-dryrun-lab` runs that same starter from any directory. It does not need `DRYRUN_HOME`. After `./ensure-running` has recorded this checkout, the same command is on your `PATH` as `start-dryrun-lab`, in a login shell and in an ordinary terminal. A **Start Dry Run Lab** icon is in the application menu. This computer has no session manager, so a login autostart entry does not start the lab. The command and the icon are the recovery that works here.

### The page will not load

The page is served at `http://127.0.0.1:8742` on this computer.

When the server is down, the window stays empty:

1. Run `start-dryrun-lab` from any directory, or double-click **Start Dry Run Lab**.
2. Open `http://127.0.0.1:8742` again. A reload after the server is up shows the devices, the topology, and the terminal.
3. If the icon is missing, run `./ensure-running` once from the repository directory. That records the checkout and installs the command and the icon.

When the server is up and the window stays empty, the browser is showing a saved copy of the page script. Press Ctrl+Shift+R to reload. If the script still does not mount, the page says `The page didn't load. Press Ctrl+Shift+R to reload.`

`DRYRUN_HOME` overrides the data directory for that command. `./ensure-running` records the directory it actually used in `.dryrun-home` in the checkout and in `$XDG_CONFIG_HOME/dryrun-lab/install-path` (`~/.config/dryrun-lab/install-path` when `XDG_CONFIG_HOME` is unset). Later shells do not need `DRYRUN_HOME`. `bin/dryrun-lab` reads the override, then the checkout record, then the user record, then `$HOME/.local/share/dryrun-lab`.

A virtualenv under that directory is reused when it matches the pinned requirements and the same Python interpreter. Those runs do not contact the package index. If that Python is missing or has changed, the virtualenv is created again. A home-folder virtualenv can survive a wipe while the interpreter it points at does not.

Data, the jar, and the virtualenv live in that directory. Logs are `ensure.log`, `batfish.log`, and `server.log` there.

## Shell

`./ensure-running` prints the CLI path. From the repo you can also use `bin/dryrun-lab` after the first successful run.

```bash
bin/dryrun-lab load examples/office-lab
bin/dryrun-lab device add R2 --role router --config configs/R2.cfg
bin/dryrun-lab device add SW4 --role switch --config configs/SW4.cfg --neighbors neighbors/SW4.txt
bin/dryrun-lab devices
bin/dryrun-lab links
bin/dryrun-lab confirm LINK_ID
bin/dryrun-lab dismiss LINK_ID
bin/dryrun-lab warnings
bin/dryrun-lab status
bin/dryrun-lab show R1 "show ip route"
bin/dryrun-lab show R1 "show ip interface brief"
bin/dryrun-lab show R1 "show running-config"
bin/dryrun-lab show SW1 "show vlan brief"
bin/dryrun-lab show SW1 "show interfaces trunk"
bin/dryrun-lab show R1 "show access-lists"
bin/dryrun-lab show R1 "ping 10.10.10.1"
bin/dryrun-lab show R1 "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30"
bin/dryrun-lab show R1 "traceroute 10.255.1.1 source 10.50.0.1"
bin/dryrun-lab host list
bin/dryrun-lab link list
```

`load <folder>` is the normal way to open a lab, including a customer pack. The office example is one folder of that shape, not a separate kind of load. The folder contains `topology.json`, a config file for each device, and optional neighbor pastes:

```text
my-lab/
  topology.json
  configs/EDGE1.cfg
  configs/CORE1.cfg
  neighbors/EDGE1.txt
```

`topology.json` lists each device with `file`, `role` (`router`, `switch`, or `host`), optional `neighbors`, and optional `x` and `y`. A host entry uses the same file layout: `Ethernet0`, an address, and `ip default-gateway`.

`device add NAME --role router|switch --config FILE` adds one router or switch and reads that config on this machine. `--neighbors FILE` attaches a CDP or LLDP paste. That is the shell equivalent of **+ Router** and **+ Switch**.

`status` prints whether the engine is up, the lab name, and the device, link, and warning counts.

The CLI only talks to `127.0.0.1` or `localhost`. It reads config files locally and posts the text to the lab. Show, ping, and traceroute transcripts are tagged `[computed]`. Lines typed in config mode are not. `bin/dryrun-lab --help` and `bin/dryrun-lab load` print the full limit. Other commands do not repeat it. The same limit stays in the lab banner. An unknown command, or a command with a pipe, is refused and the CLI exits non-zero.

`bin/dryrun-lab --version` prints the build commit, for example `dryrun-lab 7a7dd64`. The same stamp is the first line of each `ensure-running` log and sits next to the credit in the page footer. A checkout uses `git rev-parse`, and adds `-dirty` when the work tree has changes. A GitHub source archive (or any `git archive`) has no `.git` directory; the commit is written into `src/dryrun_lab/version.py` when the archive is built. A folder of loose files, with the placeholder still in that file and no `.git` directory, prints `dryrun-lab unknown`.

`configure terminal` edits that device's config. The prompt becomes `R1(config)#`, then `R1(config-if)#`, `R1(config-ext-nacl)#`, `R1(config-std-nacl)#`, `R1(config-vlan)#`, or `R1(config-router)#` in those sub-modes. The banner says `End with CNTL/Z.` `end` recomputes and prints what changed in routes, warnings, and reachability, tagged `[computed]`. `abort` discards the lines and does not recompute. `revert` undoes one `configure terminal` … `end` block on that device and recomputes. Call it again to undo the block before that. The transcript says `Reverted one edit. Recomputed.` A second `revert` with nothing left says `Nothing to revert on this device.` The same commands work in the page's device CLI. A line the device would reject, such as an invalid address, a misspelled keyword, or a glued command, is refused at the prompt with `% Invalid input detected at '^' marker.` That line is not added to the edit, and a failed edit is not written to disk. At global config, a real IOS command this lab does not apply is stored, and the prompt says `% Not simulated in this version. The line was kept.` That covers `spanning-tree` and the other forwarding lines below, and any other real IOS command word this lab does not apply, including the same command with a leading `no`. Harmless lines such as `logging host` stay quiet. A word that is not an IOS command, including a one-character misspelling, is the invalid-input case and is not stored. Inside an interface, VLAN, router, or ACL stanza that global check is not applied, so a pasted body stays intact. A forwarding line there is flagged when the edit is committed.

An inbound ACL is tested with `source` and `ingress`. The source is a host in the denied subnet, and `ingress` is the interface where the ACL is applied inbound. A ping that starts on the router itself does not pass through that inbound list.

The reachability block after `end` or `revert` may use a sample host, such as `10.99.0.50`, instead of a configured address such as `10.99.0.1`. The line says so. A trace to the configured address stops on the device that owns it. The sample is another host on that subnet, so the check can show whether traffic is delivered or denied.

To check that a revert restored a device, save `show running-config` (and the ping you care about) before the edit, revert, then run the same commands and diff them. Matching output means that device is back where it was. `status`, `links`, and `warnings` cover the rest of the lab.

```bash
bin/dryrun-lab show R1 "show running-config" > /tmp/r1-before.txt
bin/dryrun-lab show R1 "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30" > /tmp/ping-before.txt
bin/dryrun-lab show R1 $'configure terminal\nip access-list extended GUEST-IN\n25 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255\nend'
bin/dryrun-lab show R1 "show access-lists"
bin/dryrun-lab show R1 "ping 10.99.0.1 source 10.30.30.50 ingress GigabitEthernet0/0.30"
bin/dryrun-lab show R1 $'configure terminal\nip access-list extended GUEST-IN\n26 deny ip 10.30.30.0 0.0.0.255 10.99.0.0 0.0.0.255\nabort'
bin/dryrun-lab show R1 revert
bin/dryrun-lab show R1 "show running-config" > /tmp/r1-after.txt
diff -u /tmp/r1-before.txt /tmp/r1-after.txt
```

`abort` prints `Configuration aborted. Nothing was applied.` The sequence typed before `abort` is not in `show access-lists`. `25` is inserted between the existing sequence 20 and sequence 30. A line without a number is appended instead.

```bash
bin/dryrun-lab show R1 $'configure terminal\ninterface GigabitEthernet0/0\n shutdown\nend'
bin/dryrun-lab show R1 revert
```

Supported device-CLI commands: `show running-config`, `show ip interface brief`, `show ip route`, `show vlan brief`, `show interfaces trunk`, `show access-lists`, `show ip ospf neighbor`, `show warnings`, `ping`, `traceroute`, `configure terminal`, and `revert`. Pipes are refused. A show command this lab does not compute says it is not simulated in this version. Interface lists use natural port order, so Gi1/0/2 comes before Gi1/0/10. Config keywords are accepted in any case and stored lowercase. Names, such as an ACL name, keep the case you typed.

`show access-lists` always prints sequence numbers (`10`, `20`, `30`, …). A line typed in `ip access-list` mode without a number is appended and gets the last sequence plus 10. A line that starts with a number is inserted at that sequence. From IOS-XE 16.12, sequence numbers are nvgened: `show running-config` and the config panel show a sequence number on every ACL entry. Remarks are numbered on 16.12 and later. That remark behavior is unconfirmed. On an older version line, `show running-config` prints the ACL entries without sequence numbers. The saved config keeps a number when you typed it, when `ip access-list resequence` wrote it, or when leaving it off would assign a different sequence on the next read, which happens after an earlier line is removed. A router or a switch with no `version` line uses the 16.12 behavior and shows `No version line found; assuming IOS-XE 16.12 or later`. A host does not show that note. `no 25` and `no deny ip …` remove an entry. `ip access-list resequence NAME START STEP` renumbers that list and stores the new numbers. A resequence command this lab does not apply is left in the config and reported as not simulated. A new entry that can never match, because an earlier line already matches everything it would, is called out when the edit is committed, including in the Warnings section of the change summary.

A host is an end device: one interface address and `ip default-gateway`. Add one from the shell, or with **+ Host** on the page. The page requires the name, the IP address, the mask, and the gateway. A new host starts below the other cards. `link add` moves it under the switch or router that cable attaches to, so a server cabled to SW3 sits with SW3. On the canvas, click one port dot and then the other port dot to draw a cable. Click the cable itself to remove it. Drawing, removing, confirming, or rejecting a cable prints the same recompute summary: a first line (`Cabled`, `Removed`, `Confirmed`, or `Rejected`), then Routes, Warnings, and Reachability. While that recompute runs, the page says `Adding cable…`, `Removing cable…`, `Confirming cable…`, or `Rejecting cable…` and ignores a second click. Dragging a card moves the device.

CDP and LLDP pastes do not suggest host cables. A host cable is suggested when the host address is in an access VLAN's subnet and that switch port's description matches the host (the host name is in the description, or the description's words and number match, such as `POS register 1` for `POS-01`). Confirm it like any other suggestion. If the description does not match, draw the cable yourself with the port dots or `link add`. A switch that has `ip default-gateway` is still a switch when the config contains switchport or vlan commands, including the indented switchport lines on an access port. The page refreshes on its own when the lab changes through the CLI or the API.

Cable labels say `confirmed` or `suggested`. A solid green line is confirmed. A dashed orange line is suggested. A red count on a device is lines that were not simulated. An orange `ignored` badge means `ip default-gateway` was ignored because `ip routing` is enabled.

The config panel hides passwords, secrets, SNMP communities, and authentication keys for OSPF, BGP, NTP, ISAKMP, HSRP, TACACS, and RADIUS, including a `key` line under `tacacs server` or `radius server`. That mask is on by default, including in the device CLI output, so a screenshot of the page does not show them. Turn **Mask secrets** off to read or edit those lines. Saving while the mask is on keeps the real config.

```bash
bin/dryrun-lab host add PC40 --ip 10.40.40.50/24 --gw 10.40.40.1
bin/dryrun-lab host add SRV20 --ip 10.20.20.50/24 --gw 10.20.20.1
bin/dryrun-lab link add PC40 Ethernet0 SW2 Gi0/12
bin/dryrun-lab link unconfirm LINK_ID
bin/dryrun-lab link delete LINK_ID
bin/dryrun-lab host delete PC40
```

`link add` writes a confirmed cable. `links` lists suggestions too. `confirm LINK_ID` accepts a suggestion. `link unconfirm LINK_ID` sets a confirmed cable back to suggested and withdraws it from the layer-1 file. A cable you drew stays in the list. A cable the lab inferred shows up again as a suggestion. If the cable is already suggested, the command says so and exits cleanly. `dismiss LINK_ID` rejects one so it is not inferred again.

What is actually connected:

- A confirmed cable is a layer-1 edge. Suggested trunks, access ports, and host cables are not. A host ping uses confirmed cables, including the ones `link add` created. Confirm the office trunks on that path before the ping. The layer-2 line under a host trace walks confirmed cables only. A host with no confirmed link is labeled **Not modeled**.
- A shared `/30` or `/31` with exactly two physical interfaces is also written while that cable is still suggested. The office OSPF link (`10.50.0.0/30`, R1 Gi0/2 to SW1 Gi1/0/24) is one of these, so OSPF and `traceroute 10.255.1.1 source 10.50.0.1` succeed before you confirm it. Confirming another cable, including the R1–SW1 trunk, does not remove it. `unconfirm` withdraws that edge after the cable has been confirmed. While it is still only suggested, `unconfirm` leaves the edge in place and `dismiss` removes the suggestion. If that was the only layer-1 edge, the file is empty again and the hub below can reconnect those interfaces.
- When a computed result uses that unconfirmed cable, the text says so. `show ip route`, `ping`, `traceroute`, and a change summary that added, removed, or rechecked a path across it include a line such as `assumed link from shared /30: R1 Gi0/2 - SW1 Gi1/0/24 (not confirmed)`. The device CLI on the page prints that same line. A connected route on the interface, or a ping that stays on one device, does not. Confirming the cable removes the sentence.
- While the layer-1 file has no edges, the engine does not read the suggestion list. It treats physical interfaces as if they shared one hub, so other shared subnets can look adjacent too. That is a fallback for an empty file, not a confirmed cable. A ping whose source and destination are both addresses on the same device, such as `ping 10.20.20.1 source 10.10.10.50 ingress GigabitEthernet0/0.10` on R1, does not use a cable at all.

Ping and traceroute print one sentence under the disposition. A drop names the ACL and its sequence number. When the trace starts on a host, a following line lists the layer-2 path across confirmed links and computed VLAN membership. Switches on that line are not hops in the computed trace. A shut or down cable is drawn red and dashed after the next recompute. A host with no address, no gateway, or no confirmed link is labeled **Not modeled**.

### VLAN 40 host path

The office example has no VLAN 40. This is the setup the host test uses. Confirm the R1–SW1, SW1–SW2, and SW1–SW3 cables (`bin/dryrun-lab links`, then `confirm` on each id) before the host ping. `link add` confirms the two new host cables itself.

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

SRV20 uses the existing VLAN 20 access port on SW3 Gi0/10. VLAN 40 has to be allowed on both SW1–SW2 and SW1–R1. The computed traceroute hops are the host, the router, and the server. Switches are named on the layer-2 line, not as hops.

## Office lab

`examples/office-lab/` is synthetic. Addresses are from `10.0.0.0/8` or the documentation ranges `192.0.2.0/24` and `203.0.113.0/24`.

One router (router-on-a-stick, OSPF on a `/30`, one extended ACL) and three switches (VLANs, trunks, access ports). Load it from the UI with **Load office lab**, or with the CLI command above. Dashed cables are suggestions. Confirm or dismiss each one. Shared management subnets are notes, not cables.

Each example device contains `ip default-gateway`. The lab reads that device's config: if `ip routing` is enabled, the line is **ignored when ip routing is enabled** (R1 and SW1). On a switch with `ip routing` off (SW2 and SW3), the gateway is used for traffic that starts on the switch, and `show ip route` prints `Default gateway is 10.99.0.1`. Typing `hostname` replaces that line and the prompt. The device keeps its name in the lab, so its routes stay with that device.

Lines that can change forwarding, and that this lab does not apply, are listed as **not simulated**. That group is `spanning-tree` (including `spanning-tree mode rapid-pvst` and `spanning-tree portfast`), `storm-control`, `switchport port-security`, `switchport block`, `switchport voice`, `ip dhcp snooping`, `ip arp inspection`, `ip verify unicast`, `ip helper-address`, `ip nat`, `ip directed-broadcast`, `ip policy route-map`, `standby`, `vrrp`, `glbp`, `channel-group`, `udld`, `mac access-group`, `policy-map`, `class-map`, `service-policy`, `mls qos`, `vtp mode`, `vlan access-map`, `vlan filter`, `dot1x`, `mab`, and `authentication port-control`. The office access ports include `spanning-tree portfast`, so those lines show up on SW2 and SW3. Each copy is its own warning. SW2 has the line on Gi0/10, Gi0/11, and Gi0/20, and each of those lines is flagged. The same `ip helper-address` on two SVIs is two warnings. The warning file is `configs/SW2.cfg`, the same path as the other warnings for that device. The same text on another interface or another device is not folded into the first one. Typing `ip helper-address` in config mode keeps the line. At global config the prompt says it was not simulated. Under an interface the prompt stays quiet and the warning appears when the edit is committed.

Lines with no effect on the forwarding this lab computes are kept and are not flagged. That group is `logging` (including `logging host`), `snmp-server`, `ntp`, `banner`, `username`, `enable secret`, `enable password`, `line`, `alias`, `service`, `clock`, `boot`, `license`, `archive`, `parser`, and `ip domain`.

## What this stage computes

- A canvas for routers, switches, hosts, and interface-to-interface cables
- Link suggestions from interface descriptions, pasted CDP or LLDP text, a shared `/30` with exactly two physical interfaces, and a host cable when the host address is in an access VLAN and the port description matches, plus confirm and dismiss
- Hosts and cables from the page or from `host add`, `device add`, and `link add`, and `link unconfirm` to make a confirmed cable suggested again
- A page that refreshes when the lab changes through the CLI or the API
- Per-device config paste, with parse warnings kept visible
- Device CLI: `show running-config`, `show ip interface brief`, `show ip route`, `show vlan brief`, `show interfaces trunk`, `show access-lists`, `show ip ospf neighbor`, `show warnings`, `ping`, `traceroute`, `configure terminal`, and `revert`
- The same actions from `dryrun-lab`

## Engine

The service is the official Batfish all-in-one jar, `org.batfish.allinone.Main`, on the distro OpenJDK 21 with `-Xmx2g`. It binds the coordinator to `127.0.0.1:9996`.

GitHub release `v2026.08.27` publishes no jar, and Maven Central has no `org.batfish` artifacts. `tools/fetch_batfish.py` downloads the jar, question templates, and the matching pybatfish wheel from one pinned `batfish/allinone` image layer on Docker Hub (`sha256:53a5a598343f477bae7c97f39174d545529d2d080ed30ec3652c6e3e7ae0ac70`). It checks that layer and the jar (`sha256:7552e1380e79379b17e200b80d84c1671f689cb63a0d338678c1c4675157310f`) and stops if either hash differs. It does not fall back to a floating tag, and it does not start a container.

Plain Java is the runtime that works here. The bytecode in that layer is Java 21, the host OpenJDK 21 starts it, and the office lab computes. If that process does not open port 9996, `./ensure-running` stops and points at `ensure.log` and `batfish.log`. It does not try Docker. `./ensure-running --engine docker` starts the official image `batfish/allinone:v2026.08.27` instead. That path is untested.

The Java process uses `-Xms256m` and `-Xmx2g`. The 2 GB figure is the heap cap, not the memory in use. Resident size moves as the process computes, and the JVM does not always return heap to the OS. Virtual size is address space, about 5.6 GB here, and is not the RAM in use.

One measurement just after a first office-lab load was 476 MB resident (`VmRSS` 486,976 kB) with a high-water mark of 505 MB (`VmHWM` 516,680 kB). That is not a steady figure. The same process keeps heap it has already touched. After further office-lab computes and the test suite, one process here was at `VmRSS` 1,128,924 kB (about 1.1 GB) with a high-water mark of `VmHWM` 1,476,420 kB (about 1.4 GB). A separate longer session was about 916 MB. All of those are under the 2 GB heap cap.

## Layout

Python and FastAPI serve the API and the built UI, because pybatfish is the official client and one extra process is enough next to the JVM. The UI is React, TypeScript, and Tailwind, built with Vite into `src/dryrun_lab/static` and served from the lab process. A machine that only runs the lab does not need Node. Fonts and the terminal are local. There is no runtime CDN.

Rebuild the UI, when you change it, with:

```bash
cd frontend && npm install && npm run build
```

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pytest "$DRYRUN_HOME/batfish"/pybatfish-*.whl
.venv/bin/pytest
```

`tests/test_engine_office.py` runs only when something is already listening on `127.0.0.1:9996`. The lab install does not pull a test runner.

`pytest` also runs the frontend mask and cable checks when `node` is 22.6 or newer. Those scripts need Node's type stripping, which arrived in 22.6. An older Node, or no `node` on `PATH`, skips that one test and prints the command below. Run the same checks by themselves from `frontend/`:

```bash
cd frontend && npm test
```

`npm test` runs `node --experimental-strip-types src/mask.test.ts` and `node --experimental-strip-types src/cables.test.ts`.

## Assistant template

`bot/instructions.md` and `bot/skills/getting-started/SKILL.md` tell an assistant on this computer to run `./ensure-running` from the repository root before any lab command. That includes after a restart and after an Update Bot's Computer wipe. The skill does not open a browser unless someone asked for `--open`.

## Not tested here

A real computer restart, an Update Bot's Computer wipe, and a fresh assistant template that has never seen this checkout were not run. `./ensure-running` is the command those cases need.

## License

Apache License 2.0. See `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES`.
