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

Open that URL on the same machine. The server listens on `127.0.0.1` only. The page fills the browser window. On a desktop, `bin/open-lab` opens it maximized, and `./ensure-running` does that when a display is available.

Run it again any time. If the engine and the lab are already healthy, it leaves them running and prints the same URL.

Data, the jar, and the virtualenv live in `$DRYRUN_HOME` (default `$HOME/.local/share/dryrun-lab`). Logs are `ensure.log`, `batfish.log`, and `server.log` in that directory.

## Shell

`./ensure-running` prints the CLI path. From the repo you can also use `bin/dryrun-lab` after the first successful run.

```bash
bin/dryrun-lab load examples/office-lab
bin/dryrun-lab devices
bin/dryrun-lab links
bin/dryrun-lab warnings
bin/dryrun-lab show R1 "show ip route"
bin/dryrun-lab show R1 "show ip interface brief"
bin/dryrun-lab show R1 "show running-config"
```

The CLI only talks to `127.0.0.1` or `localhost`. It reads config files locally and posts the text to the lab. Each show transcript is tagged `[computed]`. The full limit stays in the lab banner.

Supported device-CLI commands in this stage: `show running-config`, `show ip interface brief`, `show ip route`, and `show warnings`. Pipes are refused.

## Office lab

`examples/office-lab/` is synthetic. Addresses are from `10.0.0.0/8` or the documentation ranges `192.0.2.0/24` and `203.0.113.0/24`.

One router (router-on-a-stick, OSPF on a `/30`, one extended ACL) and three switches (VLANs, trunks, access ports). Load it from the UI with **Load office lab**, or with the CLI command above. Dashed cables are suggestions. Confirm or dismiss each one. Shared management subnets are notes, not cables.

Each example device contains `ip default-gateway`. Batfish reports that line as not simulated. The UI lists those lines in red under **These lines were NOT simulated**.

## What this stage computes

- A canvas for routers, switches, and interface-to-interface cables
- Link suggestions from interface descriptions, pasted CDP or LLDP text, and a shared `/30` with exactly two physical interfaces
- Per-device config paste, with parse warnings kept visible
- One device CLI (`show running-config`, `show ip interface brief`, `show ip route`)
- The same actions from `dryrun-lab`

## Engine

The service is the official Batfish all-in-one jar, `org.batfish.allinone.Main`, on the distro OpenJDK 21 with `-Xmx2g`. It binds the coordinator to `127.0.0.1:9996`.

GitHub release `v2026.08.27` publishes no jar, and Maven Central has no `org.batfish` artifacts. `tools/fetch_batfish.py` downloads the jar, question templates, and the matching pybatfish wheel from the official `batfish/allinone` image layer on Docker Hub. It does not start a container.

Plain Java is the runtime that works here. The bytecode in that layer is Java 21, the host OpenJDK 21 starts it, and the office lab computes. `ensure-running` starts the official container only if that Java process does not open port 9996. The container path was not needed for stage 1.

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

## Later

Still to build, on purpose: VLAN and trunk show commands, access-list show commands, computed ping and traceroute, config edits with a before/after diff, and the milestone labs (a VLAN end to end, an ACL that blocks a flow, a trunk that drops reachability). Packaging for an assistant template comes after that.

## License

Apache License 2.0. See `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES`.
