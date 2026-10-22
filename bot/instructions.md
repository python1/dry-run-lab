# Dry Run Lab

Created by Paul Charydczak.

This computer runs Dry Run Lab locally. Before any lab command, follow the getting-started skill: clone the repository or unpack a source archive of `main`, run `./ensure-running` from the repository root, then load `examples/office-lab` if the lab is empty. Do that on every use. `./ensure-running` is required after a computer restart and after an Update Bot's Computer wipe. It uses sudo to install OpenJDK 21 when Java is missing.

Do not pass `--open` unless someone asked to see the page. Do not connect to a real network device. Configs in this repository are synthetic. Hosts are end devices. Add one with `bin/dryrun-lab host add NAME --ip ADDR/PREFIX --gw GATEWAY` and a cable with `bin/dryrun-lab link add DEVICE INTERFACE DEVICE INTERFACE`. `link add` places the host under that device. Confirm suggested trunks before a host ping. A shared /30 or /31 stays in the layer-1 file while that cable is only suggested. Confirming another cable does not remove it. `bin/dryrun-lab link unconfirm LINK_ID` withdraws that edge after the cable has been confirmed. `dismiss` removes a suggestion; if no other layer-1 edge remains, an empty file hubs physical interfaces again.

Computed results are a simulation from these configs. They are not proof that a live network will behave the same way. Not affiliated with or endorsed by Cisco.
