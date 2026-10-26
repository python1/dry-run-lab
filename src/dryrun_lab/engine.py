"""Talk to a local Batfish service. Configs never leave this machine."""

from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dryrun_lab.acls import (
    ace_at_index,
    added_aces,
    numbered_config,
    parse_acls,
    sequence_of,
    shadow_sentence,
    split_sequence,
)
from dryrun_lab.configedit import apply_config_lines, prompt_for
from dryrun_lab.configparse import canonical_interface, parse_config
from dryrun_lab.constants import COMPUTED_TAG, ENGINE_HOST, ENGINE_PORT
from dryrun_lab.facts import annotate_warnings, routing_enabled
from dryrun_lab.hosts import gateway_address, host_document, host_limits
from dryrun_lab.ioscheck import canonical_line, invalid_input, is_harmless, kept_note, unmodeled_lines
from dryrun_lab.infer import endpoint_key
from dryrun_lab.l2path import layer2_note, unattached_host
from dryrun_lab.paths import data_home
from dryrun_lab.probes import Probe, probes_for_acl, probes_for_commands, probes_for_lab
from dryrun_lab.showfmt import (
    assumed_line,
    assumed_lines_for_route_changes,
    assumed_lines_for_routes,
    assumed_lines_for_trace,
    command_disposition,
    command_help,
    format_change_diff,
    format_ping,
    format_traceroute,
    normalize_command,
    parse_flow,
    show_access_lists,
    show_ip_ospf_neighbor,
    show_interfaces_trunk,
    show_ip_interface_brief,
    show_ip_route,
    show_running_config,
    show_unsimulated,
    show_vlan_brief,
    vlan_names,
    with_assumed,
)
from dryrun_lab.store import Lab, Link, push_config

log = logging.getLogger("dryrun_lab.engine")


class EngineUnavailable(RuntimeError):
    pass


_CONFIG_ENTER = {"configure terminal", "configure", "conf t", "conf term", "conf terminal"}


@dataclass
class ShowResult:
    text: str
    prompt: str
    changed: bool = False
    ok: bool = True


class Engine:
    def __init__(self, host: str = ENGINE_HOST, port: int = ENGINE_PORT, network: str = "dryrun") -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", network):
            raise ValueError(network)
        self.host = host
        self.port = port
        self.network = network
        self._lock = threading.Lock()
        self._session: Any = None
        self._interfaces: dict[str, list[dict[str, Any]]] = {}
        self._routes: dict[str, list[dict[str, Any]]] = {}
        self._vlans: dict[str, list[dict[str, Any]]] = {}
        self._drafts: dict[str, list[str]] = {}
        self._reach_assumed: dict[str, list[str]] = {}
        self._ready = False

    def healthy(self) -> bool:
        probe = socket.socket()
        probe.settimeout(0.4)
        try:
            probe.connect((self.host, self.port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def close(self) -> None:
        """Delete a test network. The live lab network is left in place."""
        if not self.network.startswith("dryrun-test-"):
            return
        active: set[str] = set()
        try:
            with self._lock:
                session = self._client()
                for name in list(session.list_networks()):
                    if str(name).startswith("dryrun-test-"):
                        session.delete_network(str(name))
                active = {str(name) for name in session.list_networks()}
        except Exception:
            log.exception("could not delete test network %s", self.network)
        finally:
            _sweep_test_directories(active)
            self._session = None
            self._ready = False

    def recompute(self, lab: Lab) -> None:
        if not lab.devices:
            self._interfaces = {}
            self._routes = {}
            self._vlans = {}
            self._ready = False
            lab.warnings = []
            lab.engine_error = None
            return
        if not self.healthy():
            lab.engine_error = "Analysis engine is not running on 127.0.0.1:%s." % self.port
            self._ready = False
            return
        try:
            with self._lock:
                snapshot = self._write_snapshot(lab)
                session = self._client()
                session.set_network(self.network)
                session.init_snapshot(str(snapshot), name="lab", overwrite=True)
                warnings = _warnings(session)
                self._interfaces = _interfaces(session)
                self._routes = _routes(session)
                self._vlans = _vlans(session)
                self._ready = True
            lab.warnings = _attach_devices(warnings, lab)
            lab.warnings.extend(host_limits(lab))
            lab.warnings.extend(self._unreachable_warnings(lab))
            _mark_link_state(lab, self._interfaces)
            lab.engine_error = None
        except Exception as exc:  # Batfish client raises its own types
            log.exception("recompute failed")
            lab.engine_error = f"Analysis failed: {exc}"
            self._ready = False

    def summarize_mutation(self, lab: Lab, mutate, headline: str, extra: list[Probe] | None = None) -> str:
        """Recompute after `mutate` and return the same summary a config edit prints."""
        from dryrun_lab.store import apply_inference

        self._ensure_ready(lab)
        probes = _unique_probes(probes_for_lab(lab) + list(extra or []))
        before_routes = _snap_routes(self._routes)
        before_warnings = [dict(row) for row in lab.warnings]
        self._reach_assumed = {}
        before_reach = {probe.label(): self._reach_summary(lab, probe) for probe in probes}
        assumed = _assumed_links(lab)
        mutate()
        apply_inference(lab)
        self.recompute(lab)
        after_probes = _unique_probes(probes + probes_for_lab(lab) + list(extra or []))
        after_reach = {probe.label(): self._reach_summary(lab, probe) for probe in after_probes}
        for label, summary in before_reach.items():
            after_reach.setdefault(label, summary)
        missing = {label: "not present" for label in after_reach if label not in before_reach}
        before_reach.update(missing)
        notes = _assumed_notes(
            assumed,
            _assumed_links(lab),
            assumed_lines_for_route_changes(before_routes, _snap_routes(self._routes), assumed + _assumed_links(lab)),
            _changed_reach_notes(before_reach, after_reach, self._reach_assumed),
        )
        return format_change_diff(
            before_routes,
            _snap_routes(self._routes),
            before_warnings,
            [dict(row) for row in lab.warnings],
            before_reach,
            after_reach,
            1,
            headline=headline,
            assumed=notes,
        )

    def show(self, lab: Lab, device_name: str, command: str) -> str:
        return self.show_result(lab, device_name, command).text

    def show_result(self, lab: Lab, device_name: str, command: str) -> ShowResult:
        device = lab.device(device_name)
        if device is None:
            raise KeyError(device_name)
        pieces = command.replace("\r\n", "\n").split("\n")
        pieces = [piece for piece in pieces if piece.strip()] or [command]
        texts: list[str] = []
        prompt = f"{_cli_name(device)}#"
        changed = False
        ok = True
        for piece in pieces:
            prompt, text, piece_changed, piece_ok = self._dispatch(lab, device, piece)
            changed = changed or piece_changed
            ok = ok and piece_ok
            if text:
                texts.append(text)
        if not texts:
            texts.append(_wrap(device.name, command, ""))
        return ShowResult("\n".join(texts), prompt, changed, ok)

    def _dispatch(self, lab: Lab, device: Any, command: str) -> tuple[str, str, bool, bool]:
        key = device.name.lower()
        folded = " ".join(command.strip().split()).lower()
        draft = self._drafts.get(key)
        enable = f"{_cli_name(device)}#"
        if draft is not None:
            return self._config_line(lab, device, command, draft)
        if folded in _CONFIG_ENTER:
            self._drafts[key] = []
            text = _wrap(
                device.name,
                command,
                "Enter configuration commands, one per line. End with CNTL/Z.\n",
                prompt=enable,
                computed=False,
            )
            return f"{_cli_name(device)}(config)#", text, False, True
        if folded in {"revert", "rollback"}:
            return enable, self._revert(lab, device, command), True, True
        flow = parse_flow(command)
        if flow is not None:
            self._ensure_ready(lab)
            body, drop = self._flow_body(lab, device.name, flow)
            formatter = format_ping if flow["kind"] == "ping" else format_traceroute
            shown = with_assumed(
                formatter(str(flow["dst"]), flow["src"], flow["ingress"], body, drop),
                assumed_lines_for_trace(body, _assumed_links(lab)),
            )
            text = _wrap(device.name, command, shown)
            return enable, text, False, True
        kind = normalize_command(command)
        if kind is None:
            if "|" in command:
                detail = "% Pipes are not simulated in this version.\n\n" + command_help(device.role)
            elif command_disposition(command) == "unmodeled":
                detail = "% Not simulated in this version.\n\n" + command_help(device.role)
            else:
                detail = "% Invalid input detected at '^' marker.\n\n" + command_help(device.role)
            return enable, _wrap(device.name, command, detail), False, False
        if kind == "running-config":
            rows = [row for row in lab.warnings if row.get("device") == device.name]
            return enable, _wrap(
                device.name,
                command,
                show_running_config(device.config, rows, role=device.role),
            ), False, True
        if kind == "warnings":
            rows = [row for row in lab.warnings if row.get("device") == device.name]
            return enable, _wrap(device.name, command, show_unsimulated(device.name, rows)), False, True
        if kind == "acl":
            rows = self._interfaces.get(key, [])
            return enable, _wrap(device.name, command, show_access_lists(device.config, rows)), False, True
        if kind == "ospf-neighbor":
            self._ensure_ready(lab)
            body = show_ip_ospf_neighbor(self._ospf_neighbors(device.name))
            return enable, _wrap(device.name, command, body), False, True
        self._ensure_ready(lab)
        if kind == "interfaces":
            body = show_ip_interface_brief(self._interfaces.get(key, []))
        elif kind == "vlan":
            body = show_vlan_brief(
                self._vlans.get(key, []),
                vlan_names(device.config),
                self._interfaces.get(key, []),
            )
        elif kind == "trunk":
            body = show_interfaces_trunk(self._interfaces.get(key, []))
        else:
            rows = self._routes.get(key, [])
            body = with_assumed(
                show_ip_route(rows, config=device.config, role=device.role),
                assumed_lines_for_routes(device.name, rows, _assumed_links(lab)),
            )
        return enable, _wrap(device.name, command, body), False, True

    def _client(self) -> Any:
        if self._session is not None:
            return self._session
        logging.getLogger("pybatfish").setLevel(logging.ERROR)
        from pybatfish.client.session import Session

        self._session = Session(host=self.host, port=self.port)
        return self._session

    def _ensure_ready(self, lab: Lab) -> None:
        if self._ready:
            return
        if lab.devices and self.healthy():
            self.recompute(lab)
        if self._ready:
            return
        if lab.engine_error:
            raise EngineUnavailable(lab.engine_error)
        raise EngineUnavailable("Nothing has been computed yet.")

    def _config_line(self, lab: Lab, device: Any, command: str, draft: list[str]) -> tuple[str, str, bool, bool]:
        key = device.name.lower()
        folded = " ".join(command.strip().split()).lower()
        enable = f"{_cli_name(device)}#"
        current = prompt_for(_cli_name(device, draft), draft)
        if "|" in command:
            detail = "% Pipes are not simulated in this version.\n\n" + command_help(device.role)
            return current, _wrap(device.name, command, detail, prompt=current), False, False
        if folded == "abort":
            self._drafts.pop(key, None)
            return (
                enable,
                _wrap(
                    device.name,
                    command,
                    "Configuration aborted. Nothing was applied.\n",
                    prompt=current,
                    computed=False,
                ),
                False,
                True,
            )
        if folded == "end" or (folded == "exit" and _config_depth(draft) == 1):
            lines = list(draft)
            self._drafts.pop(key, None)
            body = self._apply(lab, device, lines)
            failed = body.startswith("Change was not kept")
            changed = not failed and not body.startswith("No configuration changes")
            enable = f"{_cli_name(device)}#"
            return enable, _wrap(device.name, command, body, prompt=current, computed=changed), changed, not failed
        if folded in {"revert", "rollback"}:
            return (
                current,
                _wrap(
                    device.name,
                    command,
                    "Leave configuration mode before revert.\n",
                    prompt=current,
                    computed=False,
                ),
                False,
                True,
            )
        if folded == "exit":
            draft.append("exit")
            return (
                prompt_for(_cli_name(device, draft), draft),
                _wrap(device.name, command, "", prompt=current, computed=False),
                False,
                True,
            )
        rejected = invalid_input(draft, command.strip())
        if rejected:
            return (
                current,
                _wrap(device.name, command, rejected, prompt=current, computed=False),
                False,
                False,
            )
        canon = canonical_line(draft, command.strip())
        duplicate = _duplicate_sequence(device.config, draft, canon)
        if duplicate:
            return (
                current,
                _wrap(device.name, command, duplicate, prompt=current, computed=False),
                False,
                False,
            )
        note = kept_note(draft, canon) or ""
        draft.append(canon)
        return (
            prompt_for(_cli_name(device, draft), draft),
            _wrap(device.name, command, note, prompt=current, computed=False),
            False,
            True,
        )

    def _revert(self, lab: Lab, device: Any, command: str) -> str:
        history = device.config_history
        if not history:
            return _wrap(device.name, command, "Nothing to revert on this device.\n")
        previous = history.pop()
        body = self._replace_config(
            lab,
            device,
            previous,
            applied=1,
            remember=False,
            headline="Reverted one edit. Recomputed.",
        )
        if body.startswith("Change was not kept"):
            history.append(previous)
        return _wrap(device.name, command, body)

    def _apply(self, lab: Lab, device: Any, lines: list[str]) -> str:
        updated = apply_config_lines(device.config, lines)
        if updated == device.config:
            return "No configuration changes.\n"
        return self._replace_config(lab, device, updated, applied=len(lines), remember=True, edit_lines=lines)

    def _replace_config(
        self,
        lab: Lab,
        device: Any,
        updated: str,
        applied: int,
        remember: bool,
        edit_lines: list[str] | None = None,
        headline: str | None = None,
    ) -> str:
        from dryrun_lab.store import apply_inference

        self._ensure_ready(lab)
        before_config = device.config
        try:
            return self._commit_config(
                lab,
                device,
                updated,
                applied,
                remember,
                edit_lines,
                headline,
                before_config,
            )
        except Exception as exc:
            log.exception("edit failed")
            device.config = before_config
            if remember and device.config_history and device.config_history[-1] == before_config:
                device.config_history.pop()
            try:
                apply_inference(lab)
            except Exception:
                log.exception("could not restore inference")
            return f"Change was not kept. {exc}\n"

    def _commit_config(
        self,
        lab: Lab,
        device: Any,
        updated: str,
        applied: int,
        remember: bool,
        edit_lines: list[str] | None,
        headline: str | None,
        before_config: str,
    ) -> str:
        from dryrun_lab.store import apply_inference

        assumed = _assumed_links(lab)
        self._reach_assumed = {}
        probes = _unique_probes(
            probes_for_lab(lab)
            + probes_for_acl(lab, device.name, edit_lines or [])
            + probes_for_commands(lab, edit_lines or [])
        )
        before_routes = _snap_routes(self._routes)
        before_warnings = [dict(row) for row in lab.warnings]
        before_reach = {probe.label(): self._reach_summary(lab, probe) for probe in probes}
        if remember:
            push_config(device, before_config)
        device.config = updated
        apply_inference(lab)
        self.recompute(lab)
        if lab.engine_error:
            failed = lab.engine_error
            device.config = before_config
            if remember and device.config_history:
                device.config_history.pop()
            apply_inference(lab)
            self.recompute(lab)
            return f"Change was not kept. {failed}\n"
        after_probes = _unique_probes(probes + probes_for_lab(lab))
        after_reach = {probe.label(): self._reach_summary(lab, probe) for probe in after_probes}
        for label, summary in before_reach.items():
            after_reach.setdefault(label, summary)
        missing = {label: "not present" for label in after_reach if label not in before_reach}
        before_reach.update(missing)
        _attribute_unreachable(device.name, before_config, updated, before_warnings, lab.warnings)
        notices = _notices_for_added(
            device.name, before_config, updated, lab.warnings, before_warnings
        )
        after_routes = _snap_routes(self._routes)
        assumed_after = _assumed_links(lab)
        notes = _assumed_notes(
            assumed,
            assumed_after,
            assumed_lines_for_route_changes(before_routes, after_routes, assumed + assumed_after),
            _changed_reach_notes(before_reach, after_reach, self._reach_assumed),
        )
        return format_change_diff(
            before_routes,
            after_routes,
            before_warnings,
            [dict(row) for row in lab.warnings],
            before_reach,
            after_reach,
            applied,
            headline=headline,
            notices=notices,
            assumed=notes,
        )

    def _flow_body(self, lab: Lab, device_name: str, flow: dict[str, str | None]) -> tuple[dict[str, Any], str | None]:
        missing = _unattached_trace(lab, device_name)
        if missing is not None:
            return missing, None
        trace = self._trace(device_name, str(flow["dst"]), flow.get("src"), flow.get("ingress"))
        trace = _note_unused_gateway(lab, device_name, trace)
        _rename_steps(lab, trace)
        drop = None
        if _denied(trace):
            drop = self._drop_line(lab, device_name, flow.get("src"), str(flow["dst"]))
        note = layer2_note(lab, self._interfaces, device_name, str(flow["dst"]))
        if note:
            trace["l2"] = note
        return trace, drop

    def _reach_summary(self, lab: Lab, probe: Probe) -> str:
        missing = _unattached_trace(lab, probe.device)
        if missing is not None:
            from dryrun_lab.showfmt import explain_disposition

            summary = str(missing.get("disposition") or "NOT_ATTACHED")
            sentence = explain_disposition(missing, None, probe.dst)
            if sentence:
                summary = f"{summary} — {sentence}"
            return summary
        trace = self._trace(probe.device, probe.dst, probe.src, probe.ingress)
        trace = _note_unused_gateway(lab, probe.device, trace)
        _rename_steps(lab, trace)
        bucket = self._reach_assumed.setdefault(probe.label(), [])
        for line in assumed_lines_for_trace(trace, _assumed_links(lab)):
            if line not in bucket:
                bucket.append(line)
        from dryrun_lab.showfmt import explain_disposition

        summary = str(trace.get("disposition") or trace.get("error") or "none")
        drop = None
        if _denied(trace):
            drop = self._drop_line(lab, probe.device, probe.src, probe.dst)
            if drop:
                summary = summary + "; " + " ".join(drop.split())
        sentence = explain_disposition(trace, drop, probe.dst)
        if sentence:
            summary = f"{summary} — {sentence}"
        return summary

    def _trace(self, device: str, dst: str, src: str | None, ingress: str | None) -> dict[str, Any]:
        from pybatfish.datamodel.flow import HeaderConstraints

        start = device.lower()
        if ingress:
            start = f"@enter({device.lower()}[{canonical_interface(ingress)}])"
        headers = HeaderConstraints(dstIps=dst, srcIps=src, ipProtocols=["ICMP"])
        try:
            with self._lock:
                frame = (
                    self._client()
                    .q.traceroute(startLocation=start, headers=headers, maxTraces=1)
                    .answer()
                    .frame()
                )
        except Exception as exc:
            text = str(exc)
            if "no active location" in text.lower():
                return {"ok": False, "disposition": "NO_ACTIVE_LOCATION", "steps": [], "error": "no active location"}
            last = text.strip().splitlines()[-1] if text.strip() else "trace failed"
            return {"ok": False, "disposition": "ERROR", "steps": [], "error": last[:300]}
        rows = _records(frame)
        if not rows:
            return {"ok": False, "disposition": "NONE", "steps": [], "error": "no trace"}
        traces = rows[0].get("Traces") or []
        if not isinstance(traces, list) or not traces:
            return {"ok": False, "disposition": "NONE", "steps": [], "error": "no trace"}
        trace = traces[0]
        steps: list[dict[str, Any]] = []
        for hop in trace.get("hops") or []:
            node = str(hop.get("node") or "")
            for step in hop.get("steps") or []:
                steps.append(
                    {
                        "node": node,
                        "action": step.get("action"),
                        "detail": step.get("detail") or {},
                    }
                )
        return {"ok": True, "disposition": trace.get("disposition") or "", "steps": steps, "error": None}

    def _unreachable_warnings(self, lab: Lab) -> list[dict[str, Any]]:
        """ACL lines that can never match, kept with the other warnings."""
        rows = self._reachability_rows()
        questioned = rows is not None
        if rows is None:
            rows = []
        found: list[dict[str, Any]] = []
        for device in lab.devices:
            if device.role == "host":
                continue
            hostname = parse_config(device.config).hostname
            names = [device.name]
            if hostname and hostname.lower() != device.name.lower():
                names.append(hostname)
            for acl in parse_acls(device.config):
                text_counts: dict[str, int] = {}
                for ace in acl.aces:
                    text_counts[ace.text.lower()] = text_counts.get(ace.text.lower(), 0) + 1
                for ace in acl.aces:
                    unique = text_counts[ace.text.lower()] == 1
                    matched = [
                        row
                        for row in rows
                        if any(
                            _unreachable_matches(
                                row, name, acl.name, ace.text, ace.seq, unique=unique
                            )
                            for name in names
                        )
                    ]
                    if questioned and not matched:
                        continue
                    if not questioned and not _covered_by_any(acl, ace):
                        continue
                    blockers: list[str] = []
                    for row in matched:
                        blockers.extend(_text_list(row.get("Blocking_Lines")))
                    found.append(_unreachable_warning(device.name, acl, ace, blockers))
        return found

    def _reachability_rows(self) -> list[dict[str, Any]] | None:
        try:
            with self._lock:
                frame = self._client().q.filterLineReachability().answer().frame()
            return _records(frame)
        except Exception:
            log.exception("filterLineReachability failed")
            return None

    def _ospf_neighbors(self, device_name: str) -> list[dict[str, Any]]:
        try:
            with self._lock:
                sessions = self._client().q.ospfSessionCompatibility().answer().frame()
                processes = self._client().q.ospfProcessConfiguration().answer().frame()
        except Exception:
            log.exception("ospf neighbor query failed")
            return []
        router_ids: dict[str, str] = {}
        for row in _records(processes):
            node = str(row.get("Node") or "").lower()
            router_id = str(row.get("Router_ID") or "")
            if node and router_id:
                router_ids[node] = router_id
        found: list[dict[str, Any]] = []
        for row in _records(sessions):
            local = row.get("Interface")
            remote = row.get("Remote_Interface")
            if not isinstance(local, dict):
                continue
            hostname = str(local.get("hostname") or "")
            if hostname.lower() != device_name.lower():
                continue
            remote_name = ""
            if isinstance(remote, dict):
                remote_name = str(remote.get("hostname") or "")
            found.append(
                {
                    "router_id": router_ids.get(remote_name.lower(), ""),
                    "address": str(row.get("Remote_IP") or ""),
                    "interface": str(local.get("interface") or ""),
                    "status": str(row.get("Session_Status") or ""),
                }
            )
        return found

    def _drop_line(self, lab: Lab, device_name: str, src: str | None, dst: str) -> str | None:
        from pybatfish.datamodel.flow import HeaderConstraints

        try:
            with self._lock:
                frame = (
                    self._client()
                    .q.findMatchingFilterLines(
                        nodes=device_name.lower(),
                        headers=HeaderConstraints(dstIps=dst, srcIps=src, ipProtocols=["ICMP"]),
                        action="deny",
                    )
                    .answer()
                    .frame()
                )
        except Exception:
            log.exception("findMatchingFilterLines failed")
            return None
        rows = _records(frame)
        if not rows:
            return None
        rows.sort(key=_matching_line_order)
        top = rows[0]
        acl = str(top.get("Filter") or "acl")
        reported = str(top.get("Line") or "").strip()
        sequence, ace = split_sequence(reported)
        device = lab.device(device_name)
        if sequence is None and device is not None:
            located = ace_at_index(device.config, acl, _as_int(top.get("Line_Index")))
            if located is not None and located[1].lower() == ace.lower():
                sequence = located[0]
            else:
                sequence = sequence_of(device.config, acl, reported)
        where = f"sequence {sequence}: " if sequence is not None else ""
        return f"Dropped by ACL {acl}\n  {where}{ace}\n"

    def _write_snapshot(self, lab: Lab) -> Path:
        root = data_home() / "snapshots" / _safe_name(self.network)
        if root.exists():
            shutil.rmtree(root)
        configs = root / "configs"
        configs.mkdir(parents=True)
        hosts = root / "hosts"
        wrote_host = False
        for device in lab.devices:
            safe = _safe_name(device.name)
            if device.role == "host":
                document = host_document(device.name, device.config)
                if document is None:
                    continue
                hosts.mkdir(exist_ok=True)
                (hosts / f"{safe.lower()}.json").write_text(
                    json.dumps(document, indent=2) + "\n",
                    encoding="utf-8",
                )
                wrote_host = True
                continue
            (configs / f"{safe}.cfg").write_text(_snapshot_text(device), encoding="utf-8")
        if not wrote_host and hosts.exists():
            shutil.rmtree(hosts)
        edges = [_edge(link) for link in _layer1_links(lab)]
        topo_dir = root / "batfish"
        topo_dir.mkdir()
        (topo_dir / "layer1_topology.json").write_text(
            json.dumps({"edges": edges}, indent=2) + "\n",
            encoding="utf-8",
        )
        return root


def _cli_name(device: Any, draft: list[str] | None = None) -> str:
    """Prompt hostname. The lab device name stays the engine identity."""
    name = str(device.name)
    texts = list(str(device.config).splitlines())
    if draft:
        texts.extend(draft)
    for raw in texts:
        match = re.match(r"(?i)^hostname\s+(\S+)", raw.strip())
        if match:
            name = match.group(1)
    return name


def _duplicate_sequence(config: str, draft: list[str], line: str) -> str | None:
    """IOS rejects a sequence that is already in the ACL being edited."""
    match = re.match(r"(?i)^(\d+)\s+(?:permit|deny|remark)\b", " ".join(line.split()))
    if match is None:
        return None
    name: str | None = None
    for raw in draft:
        low = " ".join(raw.strip().split()).lower()
        header = re.match(r"ip access-list (?:extended|standard) (\S+)", low)
        if header and not low.startswith("ip access-list resequence"):
            name = header.group(1)
            continue
        if low.startswith(("interface ", "router ")) or re.fullmatch(r"vlan \d+", low) or low == "exit":
            name = None
    if name is None:
        return None
    preview = apply_config_lines(config, draft)
    number = int(match.group(1))
    for acl in parse_acls(preview):
        if acl.name.lower() == name and any(ace.seq == number for ace in acl.aces):
            return "% Duplicate sequence number\n"
    return None


def _unattached_trace(lab: Lab, device_name: str) -> dict[str, Any] | None:
    reason = unattached_host(lab, device_name)
    if reason is None:
        return None
    return {
        "ok": False,
        "disposition": "NOT_ATTACHED",
        "steps": [],
        "error": None,
        "attached": reason,
    }


def _note_unused_gateway(lab: Lab, device_name: str, trace: dict[str, Any]) -> dict[str, Any]:
    if str(trace.get("disposition") or "").upper() != "NO_ROUTE":
        return trace
    device = lab.device(device_name)
    if device is None or device.role != "switch" or routing_enabled(device.config):
        return trace
    gateway = gateway_address(device.config)
    if not gateway:
        return trace
    noted = dict(trace)
    noted["gateway"] = gateway
    return noted


def _snapshot_text(device: Any) -> str:
    """Config handed to the engine.

    The hostname in that file is the lab device name, so a `hostname` edit
    changes the prompt and the displayed config without renaming the node.
    A layer-2 switch with `ip default-gateway` gets a snapshot default route
    so traffic that starts on the switch follows the gateway. The displayed
    config is unchanged.
    """
    text = numbered_config(device.config)
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    rewritten: list[str] = []
    saw = False
    for raw in lines:
        if re.match(r"(?i)^hostname\s+\S+\s*$", raw.strip()):
            if not saw:
                rewritten.append(f"hostname {device.name}")
                saw = True
            continue
        rewritten.append(raw)
    if not saw:
        rewritten.insert(0, f"hostname {device.name}")
    if device.role == "switch" and not routing_enabled(device.config):
        gateway = gateway_address(device.config)
        route = f"ip route 0.0.0.0 0.0.0.0 {gateway}" if gateway else ""
        if route and not any(line.strip().lower() == route.lower() for line in rewritten):
            _insert_snapshot_route(rewritten, route)
    body = "\n".join(rewritten).rstrip() + "\n"
    return body


def _insert_snapshot_route(lines: list[str], route: str) -> None:
    for index, line in enumerate(lines):
        if line.strip().lower() == "end":
            lines.insert(index, route)
            return
    lines.append(route)


def _wrap(
    device: str,
    command: str,
    body: str,
    *,
    prompt: str | None = None,
    computed: bool = True,
) -> str:
    shown = prompt or f"{device}#"
    head = f"{shown} {command.strip()}\n"
    if not computed:
        return head + body
    return f"{head}{COMPUTED_TAG}\n\n{body}"


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return cleaned or "device"


def _rename_steps(lab: Lab, trace: dict[str, Any]) -> None:
    for step in trace.get("steps") or []:
        device = lab.device(str(step.get("node") or ""))
        if device is not None:
            step["node"] = device.name


def _mark_link_state(lab: Lab, interfaces: dict[str, list[dict[str, Any]]]) -> None:
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for node, rows in interfaces.items():
        for row in rows:
            index[(node.lower(), canonical_interface(str(row.get("name") or "")).lower())] = row
    for link in lab.links:
        down = False
        for device_name, iface_name in (
            (link.a_device, link.a_interface),
            (link.b_device, link.b_interface),
        ):
            row = index.get((device_name.lower(), canonical_interface(iface_name).lower()))
            if row is not None:
                if row.get("admin_up") is False or row.get("active") is False:
                    down = True
                continue
            device = lab.device(device_name)
            if device is None:
                continue
            parsed = parse_config(device.config).get(iface_name)
            if parsed is not None and parsed.shutdown:
                down = True
        link.down = down


def _layer1_links(lab: Lab) -> list[Link]:
    """Edges written into the layer-1 file.

    Confirmed cables are edges. A suggested /30 or /31 between two physical
    interfaces is also an edge, unless `unconfirm` withdrew it. Suggested
    trunks and host cables are not. Writing the point-to-point edge keeps
    that adjacency when some other cable is confirmed. An empty file makes
    the engine hub every physical interface together, which is a different
    path and is not a reading of the suggestion list.
    """
    withdrawn = set(lab.withdrawn)
    chosen: list[Link] = []
    seen: set[str] = set()
    for link in lab.links:
        key = endpoint_key(link.a_device, link.a_interface, link.b_device, link.b_interface)
        if key in seen:
            continue
        if link.status == "confirmed" or (_point_to_point_subnet(link) and key not in withdrawn):
            seen.add(key)
            chosen.append(link)
    return chosen


def _assumed_links(lab: Lab) -> list[Link]:
    """Suggested /30 or /31 edges written into layer 1. Confirmed cables are not."""
    return [link for link in _layer1_links(lab) if link.status != "confirmed"]


def _changed_reach_notes(
    before: dict[str, str],
    after: dict[str, str],
    used: dict[str, list[str]],
) -> list[str]:
    notes: list[str] = []
    for label in set(before) | set(after):
        if before.get(label) == after.get(label):
            continue
        for line in used.get(label, []):
            if line not in notes:
                notes.append(line)
    return notes


def _assumed_notes(
    before_links: list[Link],
    after_links: list[Link],
    route_notes: list[str],
    reach_notes: list[str],
) -> list[str]:
    wanted = set(route_notes) | set(reach_notes)
    ordered: list[str] = []
    seen: set[str] = set()
    for link in [*before_links, *after_links]:
        line = assumed_line(link)
        if line in wanted and line not in seen:
            seen.add(line)
            ordered.append(line)
    for line in [*route_notes, *reach_notes]:
        if line not in seen and line in wanted:
            seen.add(line)
            ordered.append(line)
    return ordered


def _point_to_point_subnet(link: Link) -> bool:
    sources = {part for part in link.source.split("+") if part}
    if "subnet" not in sources:
        return False
    match = re.search(r"/(\d+)\b", link.reason)
    return bool(match and int(match.group(1)) >= 30)


def _edge(link: Link) -> dict[str, Any]:
    return {
        "node1": {
            "hostname": link.a_device.lower(),
            "interfaceName": canonical_interface(link.a_interface),
        },
        "node2": {
            "hostname": link.b_device.lower(),
            "interfaceName": canonical_interface(link.b_interface),
        },
    }


def _records(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    return json.loads(frame.to_json(orient="records"))


def _warnings(session: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    # Same text on two lines stays two warnings. The key is the file and the line.
    seen: set[tuple[str, str, str]] = set()
    try:
        parsed = _records(session.q.parseWarning().answer().frame())
    except Exception:
        log.exception("parseWarning failed")
        parsed = []
    for row in parsed:
        filename = str(row.get("Filename") or "")
        text = str(row.get("Text") or "").strip()
        line = _as_int(row.get("Line"))
        key = (filename, str(line), text)
        if key in seen or not text:
            continue
        seen.add(key)
        rows.append(
            {
                "file": filename,
                "line": line,
                "text": text,
                "detail": str(row.get("Comment") or "This line was not recognized"),
                "kind": "parse",
            }
        )
    try:
        issues = _records(session.q.initIssues().answer().frame())
    except Exception:
        log.exception("initIssues failed")
        issues = []
    for row in issues:
        kind = str(row.get("Type") or "")
        if "parse" in kind.lower():
            continue
        text = str(row.get("Line_Text") or "").strip()
        detail = str(row.get("Details") or kind)
        sources = row.get("Source_Lines") or []
        if isinstance(sources, str):
            sources = [sources]
        if not sources:
            sources = [""]
        for source in sources:
            filename, line = _split_source(str(source))
            line = _as_int(line)
            key = (filename, str(line), text or detail)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "file": filename,
                    "line": line,
                    "text": text or detail,
                    "detail": detail,
                    "kind": "convert",
                }
            )
    return rows


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_source(source: str) -> tuple[str, int | None]:
    # configs/R1.cfg:[43] or configs/R1.cfg:43
    match = re.match(r"^(?P<file>.+?):\[?(?P<line>\d+)", source)
    if not match:
        return source, None
    return match.group("file"), int(match.group("line"))


def _attach_devices(rows: list[dict[str, Any]], lab: Lab) -> list[dict[str, Any]]:
    by_file = {}
    for device in lab.devices:
        by_file[_safe_name(device.name).lower() + ".cfg"] = device.name
        by_file[device.name.lower() + ".cfg"] = device.name
    attached = []
    for row in rows:
        filename = str(row.get("file") or "")
        stem = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
        device = by_file.get(stem)
        attached.append({**row, "device": device})
    configs = {device.name: device.config for device in lab.devices}
    attached = _with_local_warnings(attached, configs)
    attached = _drop_snapshot_routes(attached, configs)
    return annotate_warnings(attached, configs)


def _drop_snapshot_routes(rows: list[dict[str, Any]], configs: dict[str, str]) -> list[dict[str, Any]]:
    """Hide a default route that exists only in the analysis snapshot."""
    kept: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip().lower()
        device = str(row.get("device") or "")
        config = configs.get(device, "").lower()
        if text.startswith("ip route 0.0.0.0 0.0.0.0") and text not in config:
            continue
        kept.append(row)
    return kept


def _with_local_warnings(rows: list[dict[str, Any]], configs: dict[str, str]) -> list[dict[str, Any]]:
    """Flag unmodeled forwarding lines, and drop lines that do not affect forwarding.

    A warning is one device and one line. The same text on another interface,
    or on another device, is a different line and stays in the list. A row
    the engine already reported for that device and line is not repeated.
    """
    kept = [row for row in rows if not is_harmless(str(row.get("text") or ""))]
    covered: set[tuple[str, int]] = set()
    for row in kept:
        device = str(row.get("device") or "")
        line = _as_int(row.get("line"))
        if device and line is not None:
            covered.add((device.lower(), line))
    for device, config in configs.items():
        for line_no, text in unmodeled_lines(config):
            key = (device.lower(), line_no)
            if key in covered:
                continue
            covered.add(key)
            kept.append(
                {
                    "file": f"configs/{_safe_name(device)}.cfg",
                    "line": line_no,
                    "text": text,
                    "detail": "not simulated",
                    "kind": "missed",
                    "device": device,
                }
            )
    return kept


_IFACE_REF = re.compile(r"^([^[]+)\[(.+)]$")


def _interfaces(session: Any) -> dict[str, list[dict[str, Any]]]:
    frame = session.q.interfaceProperties().answer().frame()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _records(frame):
        ref = row.get("Interface")
        if isinstance(ref, dict):
            node = str(ref.get("hostname") or "")
            name = str(ref.get("interface") or "")
        else:
            match = _IFACE_REF.match(str(ref or ""))
            if not match:
                continue
            node, name = match.group(1), match.group(2)
        if not node or not name:
            continue
        grouped.setdefault(node.lower(), []).append(
            {
                "name": name,
                "address": row.get("Primary_Address"),
                "active": bool(row.get("Active")),
                "admin_up": bool(row.get("Admin_Up")) if row.get("Admin_Up") is not None else True,
                "mode": row.get("Switchport_Mode"),
                "access_vlan": row.get("Access_VLAN"),
                "allowed": row.get("Allowed_VLANs"),
                "native": row.get("Native_VLAN"),
                "filter_in": row.get("Incoming_Filter_Name"),
                "filter_out": row.get("Outgoing_Filter_Name"),
            }
        )
    return grouped


def _vlans(session: Any) -> dict[str, list[dict[str, Any]]]:
    try:
        frame = session.q.switchedVlanProperties().answer().frame()
    except Exception:
        log.exception("switchedVlanProperties failed")
        return {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _records(frame):
        node = str(row.get("Node") or "").lower()
        ports: list[str] = []
        for ref in row.get("Interfaces") or []:
            if isinstance(ref, dict):
                name = str(ref.get("interface") or "")
            else:
                match = _IFACE_REF.match(str(ref or ""))
                name = match.group(2) if match else str(ref or "")
            if name:
                ports.append(name)
        grouped.setdefault(node, []).append({"vlan": row.get("VLAN_ID"), "ports": ports})
    return grouped


def _snap_routes(routes: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return {node: [dict(row) for row in rows] for node, rows in routes.items()}


def _unique_probes(probes: list[Probe]) -> list[Probe]:
    found: list[Probe] = []
    seen: set[tuple[str, str, str, str]] = set()
    for probe in probes:
        if probe.key in seen:
            continue
        seen.add(probe.key)
        found.append(probe)
    return found


def _denied(trace: dict[str, Any]) -> bool:
    if str(trace.get("disposition") or "").upper() == "DENIED":
        return True
    return any(str(step.get("action") or "").upper() == "DENIED" for step in trace.get("steps") or [])


def _config_depth(commands: list[str]) -> int:
    nested = False
    for raw in commands:
        line = raw.strip().lower()
        if line.startswith("ip access-list resequence"):
            nested = False
            continue
        if line.startswith(("interface ", "ip access-list ", "router ")) or re.fullmatch(r"vlan\s+\d+", line):
            nested = True
        elif line == "exit":
            nested = False
    return 2 if nested else 1


def _ace_key(row: dict[str, Any]) -> tuple[str, Any, str]:
    return (
        str(row.get("acl") or "").lower(),
        row.get("sequence"),
        str(row.get("ace") or "").lower(),
    )


def _as_added_line(text: str) -> str:
    prefix = "Line at sequence"
    if text.startswith(prefix):
        return "Line added at sequence" + text[len(prefix) :]
    return text


def _attribute_unreachable(
    device_name: str,
    before: str,
    after: str,
    before_warnings: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """Use 'added' only for an unreachable line this edit introduced.

    A line that was already in the config is not described as added. A
    warning already stored for the same line keeps its wording, so a later
    unrelated edit does not rewrite it.
    """
    added = {(acl.name.lower(), ace.seq, ace.text.lower()) for acl, ace in added_aces(before, after)}
    previous: dict[tuple[str, Any, str], str] = {}
    for row in before_warnings:
        if str(row.get("kind") or "") != "unreachable":
            continue
        if str(row.get("device") or "").lower() != device_name.lower():
            continue
        previous[_ace_key(row)] = str(row.get("text") or "")
    for row in warnings:
        if str(row.get("kind") or "") != "unreachable":
            continue
        if str(row.get("device") or "").lower() != device_name.lower():
            continue
        key = _ace_key(row)
        if key in previous:
            row["text"] = previous[key]
            continue
        if key in added:
            row["text"] = _as_added_line(str(row.get("text") or ""))


def _notices_for_added(
    device_name: str,
    before: str,
    after: str,
    warnings: list[dict[str, Any]],
    before_warnings: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Banner lines for unreachable ACL entries this edit caused.

    That is a line this edit introduced, or a line already in the config
    that this edit caused to stop matching. Warnings that were already
    present stay out of the banner.
    """
    added = {(acl.name.lower(), ace.seq, ace.text.lower()) for acl, ace in added_aces(before, after)}
    already: set[tuple[str, Any, str]] = set()
    for row in before_warnings or []:
        if str(row.get("kind") or "") != "unreachable":
            continue
        if str(row.get("device") or "").lower() != device_name.lower():
            continue
        already.add(_ace_key(row))
    notices: list[str] = []
    for row in warnings:
        if str(row.get("kind") or "") != "unreachable":
            continue
        if str(row.get("device") or "").lower() != device_name.lower():
            continue
        key = _ace_key(row)
        text = str(row.get("text") or "")
        if not text:
            continue
        if key in added or (before_warnings is not None and key not in already):
            notices.append(text)
    return notices


def _unreachable_warning(device_name: str, acl: Any, ace: Any, blockers: list[str]) -> dict[str, Any]:
    return {
        "device": device_name,
        "file": f"configs/{_safe_name(device_name)}.cfg",
        "line": None,
        "text": shadow_sentence(acl, ace, blockers),
        "detail": f"ACL {acl.name} sequence {ace.seq}",
        "kind": "unreachable",
        "acl": acl.name,
        "sequence": ace.seq,
        "ace": ace.text,
    }


def _covered_by_any(acl: Any, ace: Any) -> bool:
    return any(item.seq < ace.seq and item.text.lower() in {"permit ip any any", "permit any"} for item in acl.aces)


def _unreachable_matches(
    row: dict[str, Any],
    device_name: str,
    acl_name: str,
    ace_text: str,
    ace_seq: int,
    *,
    unique: bool = False,
) -> bool:
    """True when this Batfish row is this ACE, not an earlier copy of its text."""
    sources = " ".join(_text_list(row.get("Sources"))).lower()
    if acl_name.lower() not in sources:
        return False
    if device_name.lower() not in sources and ":" in sources:
        return False
    reported_seq, reported = split_sequence(str(row.get("Unreachable_Line") or ""))
    if reported.lower() != ace_text.lower():
        return False
    if reported_seq is not None:
        return reported_seq == ace_seq
    return unique


def _matching_line_order(row: dict[str, Any]) -> tuple[int, int]:
    """Earliest matching ACE. Sequence wins over an identical later line."""
    sequence, _text = split_sequence(str(row.get("Line") or ""))
    index = _as_int(row.get("Line_Index"))
    return (
        sequence if sequence is not None else 1_000_000_000,
        index if index is not None else 1_000_000_000,
    )


def _text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if hasattr(value, "tolist"):
        value = value.tolist()
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _sweep_test_directories(active: set[str] | None = None) -> None:
    """Remove Batfish leftovers from dryrun-test-* networks. Never touch dryrun."""
    keep = set(active or ())
    home = data_home()
    snap = home / "snapshots"
    if snap.is_dir():
        for child in list(snap.iterdir()):
            if child.name.startswith("dryrun-test-") and child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)
    root = home / "batfish" / "data" / "networks"
    if not root.is_dir():
        return
    ids = home / "batfish" / "data" / "ids"
    for net_dir in list(root.iterdir()):
        if not net_dir.is_dir():
            continue
        prefixes = _snapshot_prefixes(net_dir)
        if not prefixes or any(not prefix.startswith("dryrun-test-") for prefix in prefixes):
            continue
        if prefixes & keep:
            continue
        shutil.rmtree(net_dir, ignore_errors=True)
        if not ids.is_dir():
            continue
        for id_root in ids.iterdir():
            victim = id_root / net_dir.name
            if victim.exists():
                shutil.rmtree(victim, ignore_errors=True)


def _snapshot_prefixes(net_dir: Path) -> set[str]:
    found: set[str] = set()
    zips = list(net_dir.glob("original/*/snapshot.zip"))
    if not zips:
        zips = list(net_dir.rglob("snapshot.zip"))[:1]
    for zip_path in zips:
        prefix = _zip_root(zip_path)
        if prefix:
            found.add(prefix)
    return found


def _zip_root(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(30)
            if len(header) < 30 or header[:4] != b"PK\x03\x04":
                return None
            name_len = int.from_bytes(header[26:28], "little")
            name = handle.read(name_len)
    except OSError:
        return None
    text = name.decode("utf-8", errors="replace")
    root = text.split("/", 1)[0]
    return root or None


def _routes(session: Any) -> dict[str, list[dict[str, Any]]]:
    frame = session.q.routes().answer().frame()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in _records(frame):
        node = str(row.get("Node") or "").lower()
        grouped.setdefault(node, []).append(
            {
                "network": row.get("Network"),
                "next_hop": row.get("Next_Hop"),
                "protocol": row.get("Protocol"),
                "metric": row.get("Metric"),
                "admin_distance": row.get("Admin_Distance"),
                "vrf": row.get("VRF"),
            }
        )
    return grouped
