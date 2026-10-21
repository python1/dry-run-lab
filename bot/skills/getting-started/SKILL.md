---
name: getting-started
description: Start Dry Run Lab on this computer before any other lab command. Use on every lab request, after a restart, and after an Update Bot's Computer wipe.
---

# Start Dry Run Lab

On every use, before any other lab command, run this from the repository root:

```bash
./ensure-running
```

Do that even if it was already run earlier in the same conversation.

Run it again after a computer restart. Run it again after an Update Bot's Computer wipe. Nothing else starts the lab when the machine comes back.

The command is idempotent. It does not use systemd. When the analysis engine is up and a lab is saved, it reloads that lab and recomputes if this process has not computed it yet. Show commands should not need a manual reload after a restart.

It does not open a browser unless you pass `--open`. Do not pass `--open` unless someone asked to see the page. The browser path reuses an existing Dry Run Lab window, or starts one with a dedicated profile and first-run checks disabled. It never accepts terms or clicks a dialog.

A virtualenv under `$HOME/.local/share/dryrun-lab` is reused when it matches the pinned requirements and the same Python interpreter. Those runs do not contact the package index. If that Python is missing or has changed, `./ensure-running` creates the virtualenv again. A home-folder virtualenv can survive a wipe while the interpreter it points at does not.

Then use `bin/dryrun-lab` against `127.0.0.1` only. Configs stay on this machine. Do not open a session to a real device.

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.

Created by Paul Charydczak.
