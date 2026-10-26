# Office lab

Synthetic configs only. Addresses are private (`10.0.0.0/8`) or documentation ranges (`192.0.2.0/24`, `203.0.113.0/24`). Nothing here is from a real network.

These files are router and switch running-configs in the syntax the analyzer reads. Not affiliated with or endorsed by Cisco.

## Picture

```
                     R1
          Gi0/1 upstream 192.0.2.1/30
          Gi0/2 ------------ Gi1/0/24   10.50.0.0/30  (OSPF)
          Gi0/0 trunk
                     SW1
              Gi1/0/2       Gi1/0/3
                /              \
             SW2                SW3
         access 10, 30      access 20
```

R1 routes between VLANs 10, 20, 30, and 99 with dot1Q subinterfaces on `Gi0/0` (router-on-a-stick). `GUEST-IN` on VLAN 30 denies the guest subnet toward office and servers. A static default and a static route for `203.0.113.0/24` point at `192.0.2.2`. OSPF area 0 runs only on the `10.50.0.0/30` link so SW1 can advertise `10.255.1.1/32`.

## How links are inferred

| Link | Why it should be suggested |
| --- | --- |
| R1 Gi0/0 — SW1 Gi1/0/1 | Interface descriptions and CDP paste |
| SW1 Gi1/0/2 — SW2 Gi0/1 | Descriptions and LLDP paste |
| SW1 Gi1/0/3 — SW3 Gi0/1 | CDP paste only (descriptions do not name the peer) |
| R1 Gi0/2 — SW1 Gi1/0/24 | Shared `/30`, no neighbor name in the description |

VLAN 99 (`10.99.0.0/24`) is a shared management subnet, not a cable. The lab must not turn it into a full mesh.

## Lines the analyzer does not model

Each device has `ip default-gateway`. The lab checks that device's own config, not the hostname.

- R1 and SW1 contain `ip routing`. On those devices the line is reported as **ignored when ip routing is enabled**.
- SW2 and SW3 do not contain `ip routing`. Traffic that starts on those switches uses `ip default-gateway`, and `show ip route` prints `Default gateway is 10.99.0.1`.

`no ip routing` after `ip routing` makes the gateway apply to traffic that starts on the switch. Other lines in these files are parsed.
