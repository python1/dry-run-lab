# Dry Run Lab

Created by Paul Charydczak.

This computer runs Dry Run Lab locally. Before any lab command, follow the getting-started skill: find or unpack the checkout, run `./ensure-running` from the repository root, then load `examples/office-lab` if the lab is empty. Do that on every use. `./ensure-running` is required after a computer restart and after an Update Bot's Computer wipe.

Do not pass `--open` unless someone asked to see the page. Do not connect to a real network device. Configs in this repository are synthetic. Hosts are end devices. Add one with `bin/dryrun-lab host add NAME --ip ADDR/PREFIX --gw GATEWAY` and a cable with `bin/dryrun-lab link add DEVICE INTERFACE DEVICE INTERFACE`. `link add` places the host under that device. Only confirmed cables are used for layer 1, so confirm suggested trunks before a host ping. `bin/dryrun-lab link unconfirm LINK_ID` sets a confirmed cable back to suggested.

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.
