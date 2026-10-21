# Dry Run Lab

Created by Paul Charydczak.

Dry Run Lab is a local simulator for a small vendor-style network. You draw routers and switches, paste a config on each device, and confirm the cables the lab inferred. Show commands are computed on this machine by [Batfish](https://github.com/batfish/batfish). Nothing is uploaded, and the lab never opens a session to a real device.

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.

## Run it

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

A virtualenv under `$DRYRUN_HOME` (default `$HOME/.local/share/dryrun-lab`) is reused when it matches the pinned requirements and the same Python interpreter. Those runs do not contact the package index. If that Python is missing or has changed, the virtualenv is created again. A home-folder virtualenv can survive a wipe while the interpreter it points at does not.

Data, the jar, and the virtualenv live in `$DRYRUN_HOME`. Logs are `ensure.log`, `batfish.log`, and `server.log` in that directory.

## Shell

`./ensure-running` prints the CLI path. From the repo you can also use `bin/dryrun-lab` after the first successful run.

```bash
bin/dryrun-lab load examples/office-lab
bin/dryrun-lab devices
bin/dryrun-lab links
bin/dryrun-lab confirm LINK_ID
bin/dryrun-lab dismiss LINK_ID
bin/dryrun-lab warnings
bin/dryrun-lab show R1 "show ip route"
bin/dryrun-lab show R1 "show ip interface brief"
bin/dryrun-lab show R1 "show running-config"
bin/dryrun-lab show SW1 "show vlan brief"
bin/dryrun-lab show SW1 "show interfaces trunk"
bin/dryrun-lab show R1 "show access-lists"
bin/dryrun-lab show R1 "ping 10.10.10.1"
bin/dryrun-lab show R1 "traceroute 10.255.1.1 source 10.50.0.1"
bin/dryrun-lab host list
bin/dryrun-lab link list
```

The CLI only talks to `127.0.0.1` or `localhost`. It reads config files locally and posts the text to the lab. Each show, ping, and traceroute transcript is tagged `[computed]`. `bin/dryrun-lab --help` and `bin/dryrun-lab load` print the full limit. Other commands do not repeat it. The same limit stays in the lab banner.

`bin/dryrun-lab --version` prints the build commit, for example `dryrun-lab e26bcd6`. The same stamp is the first line of each `ensure-running` log and sits next to the credit in the page footer. A checkout uses `git rev-parse`, and adds `-dirty` when the work tree has changes. A packaged tree with no `.git` uses the commit written into the package. If neither is available, the stamp is `unknown`.

`configure terminal` edits that device's config. `end` recomputes and prints what changed in routes, warnings, and reachability. `abort` discards the lines. `revert` undoes one edit on that device and recomputes. Call it again to undo the edit before that. The transcript says `Reverted one edit. Recomputed.` The same commands work in the page's device CLI.

```bash
bin/dryrun-lab show R1 $'configure terminal\ninterface GigabitEthernet0/0\n shutdown\nend'
bin/dryrun-lab show R1 revert
```

Supported device-CLI commands: `show running-config`, `show ip interface brief`, `show ip route`, `show vlan brief`, `show interfaces trunk`, `show access-lists`, `show warnings`, `ping`, `traceroute`, `configure terminal`, and `revert`. Pipes are refused. Interface lists use natural port order, so Gi1/0/2 comes before Gi1/0/10.

`show access-lists` prints sequence numbers (`10`, `20`, `30`, …). A line typed in `ip access-list` mode without a number is appended and gets the last sequence plus 10. A line that starts with a number is inserted at that sequence. `show running-config` does not print those numbers, and the saved config does not gain them, unless you typed the number on that line or `ip access-list resequence` wrote the new numbers. A number is also kept when leaving it off would make the next read assign a different sequence, which happens after an earlier line is removed. `no 25` and `no deny ip …` remove an entry. `ip access-list resequence NAME START STEP` renumbers that list and stores the new numbers. A resequence command this lab does not apply is left in the config and reported as not simulated. A new entry that can never match, because an earlier line already matches everything it would, is called out when the edit is committed, including in the Warnings section of the change summary.

A host is an end device: one interface address and `ip default-gateway`. Add one from the shell, or with **Add a host** on the page. A new host starts below the other cards. `link add` moves it under the switch or router that cable attaches to, so a server cabled to SW3 sits with SW3.

```bash
bin/dryrun-lab host add PC40 --ip 10.40.40.50/24 --gw 10.40.40.1
bin/dryrun-lab host add SRV20 --ip 10.20.20.50/24 --gw 10.20.20.1
bin/dryrun-lab link add PC40 Ethernet0 SW2 Gi0/12
bin/dryrun-lab link unconfirm LINK_ID
bin/dryrun-lab link delete LINK_ID
bin/dryrun-lab host delete PC40
```

`link add` writes a confirmed cable. `links` lists suggestions too. `confirm LINK_ID` accepts a suggestion. `link unconfirm LINK_ID` sets a confirmed cable back to suggested, so it is no longer used for layer 1. A cable you drew stays in the list. A cable the lab inferred shows up again as a suggestion. If the cable is already suggested, the command says so and exits cleanly. `dismiss LINK_ID` rejects one so it is not inferred again. Only a confirmed cable is written into the layer-1 topology. A host ping uses those confirmed cables. A suggested cable is not enough, so confirm the path before the ping.

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

Each example device contains `ip default-gateway`. The lab reads that device's config: if `ip routing` is enabled, the line is **ignored when ip routing is enabled** (R1 and SW1). If it is not, the line stays in the **not simulated** list (SW2 and SW3). The hostname is not special-cased.

## What this stage computes

- A canvas for routers, switches, hosts, and interface-to-interface cables
- Link suggestions from interface descriptions, pasted CDP or LLDP text, and a shared `/30` with exactly two physical interfaces, plus confirm and dismiss
- Hosts and cables from the page or from `host add` and `link add`, and `link unconfirm` to make a confirmed cable suggested again
- Per-device config paste, with parse warnings kept visible
- Device CLI: `show running-config`, `show ip interface brief`, `show ip route`, `show vlan brief`, `show interfaces trunk`, `show access-lists`, `show warnings`, `ping`, `traceroute`, `configure terminal`, and `revert`
- The same actions from `dryrun-lab`

## Engine

The service is the official Batfish all-in-one jar, `org.batfish.allinone.Main`, on the distro OpenJDK 21 with `-Xmx2g`. It binds the coordinator to `127.0.0.1:9996`.

GitHub release `v2026.08.27` publishes no jar, and Maven Central has no `org.batfish` artifacts. `tools/fetch_batfish.py` downloads the jar, question templates, and the matching pybatfish wheel from one pinned `batfish/allinone` image layer on Docker Hub (`sha256:53a5a598343f477bae7c97f39174d545529d2d080ed30ec3652c6e3e7ae0ac70`). It checks that layer and the jar (`sha256:7552e1380e79379b17e200b80d84c1671f689cb63a0d338678c1c4675157310f`) and stops if either hash differs. It does not fall back to a floating tag, and it does not start a container.

Plain Java is the runtime that works here. The bytecode in that layer is Java 21, the host OpenJDK 21 starts it, and the office lab computes. `ensure-running` starts the official container `batfish/allinone:v2026.08.27` only if that Java process does not open port 9996, and it logs that tag. The container path was not needed for stage 1.

After `ensure-running` and a load of the office lab, the Java process used 476 MB resident (`VmRSS` 486,976 kB) and a high-water mark of 505 MB (`VmHWM` 516,680 kB). The virtual size was about 5.5 GB of address space. The heap cap is 2 GB.

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

## Assistant template

`bot/instructions.md` and `bot/skills/getting-started/SKILL.md` tell an assistant on this computer to run `./ensure-running` from the repository root before any lab command. That includes after a restart and after an Update Bot's Computer wipe. The skill does not open a browser unless someone asked for `--open`.

## Not tested here

A real computer restart, an Update Bot's Computer wipe, and a fresh assistant template that has never seen this checkout were not run. `./ensure-running` is the command those cases need.

## License

Apache License 2.0. See `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES`.
