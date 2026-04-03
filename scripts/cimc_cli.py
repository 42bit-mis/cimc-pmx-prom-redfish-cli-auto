#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

import pexpect
import yaml

PROMPT_RE = re.compile(r"(?m)^[^\r\n#]*# ?$")

def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_config(inventory_path: Path, vars_path: Path):
    inventory = load_yaml(inventory_path)
    vars_data = load_yaml(vars_path)
    host = inventory["all"]["hosts"]["localhost"]
    return host, vars_data

def normalize_disk_id(disk: str) -> str:
    return disk.split("/")[-1] if "/" in str(disk) else str(disk)

def map_raid_level(raid_level: str) -> str:
    return str(raid_level).lower().replace("raid", "")

def strip_choice(kb: int) -> str:
    return {8: "0", 16: "1", 32: "2", 64: "3", 128: "4", 256: "5", 512: "6", 1024: "7"}.get(int(kb), "")

def write_policy_choice(policy: str) -> str:
    return {
        "write_through": "0", "write-through": "0",
        "write_back": "1", "write-back": "1",
        "always_write_back": "2", "always-write-back": "2",
    }.get(str(policy).lower(), "")

def read_policy_choice(policy: str) -> str:
    return {
        "no_read_ahead": "0", "no-read-ahead": "0",
        "read_ahead": "1", "read-ahead": "1", "always": "1",
    }.get(str(policy).lower(), "")

class CimcCli:
    def __init__(self, host: str, username: str, password: str, port: int = 22, timeout: int = 60):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout
        self.child = None

    def connect(self):
        cmd = (
            f"ssh -o StrictHostKeyChecking=no "
            f"-o UserKnownHostsFile=/dev/null "
            f"-o PreferredAuthentications=password "
            f"-o PubkeyAuthentication=no "
            f"-p {self.port} {self.username}@{self.host}"
        )
        self.child = pexpect.spawn(cmd, encoding="utf-8", timeout=self.timeout)
        while True:
            idx = self.child.expect([r"yes/no", r"[Pp]assword:", PROMPT_RE, pexpect.TIMEOUT, pexpect.EOF])
            if idx == 0:
                self.child.sendline("yes")
            elif idx == 1:
                self.child.sendline(self.password)
            elif idx == 2:
                return
            elif idx == 3:
                raise RuntimeError("Timeout while connecting to CIMC CLI")
            else:
                raise RuntimeError("SSH connection closed unexpectedly while logging in")

    def close(self):
        if self.child is not None:
            try:
                self.child.sendline("exit")
                self.child.close(force=True)
            except Exception:
                pass

def run(self, command: str, timeout: int = 60) -> str:
        self.child.sendline(command)
        output_parts = []

        while True:
            idx = self.child.expect(
                [
                    r'--More--',
                    r'(?m)^[^\r\n#]*# ?$',
                ],
                timeout=timeout,
            )

            part = self.child.before.replace("--More--", "")
            output_parts.append(part)

            if idx == 0:
                self.child.send(" ")
            else:
                break

        return "".join(output_parts)

def discover_storage_slot(cli: CimcCli) -> str:
    cli.run("scope chassis")
    out = cli.run("show storageadapter detail")
    slots = re.findall(r"\bSLOT[-A-Z0-9_]+\b", out)
    if not slots:
        slots = re.findall(r"\bMEZZ\b", out)
    if not slots:
        raise RuntimeError("Could not auto-discover storage adapter slot")
    return slots[0]

def parse_virtual_drives(text: str):
    vds = []
    current = None
    for line in text.splitlines():
        line = line.rstrip()
        m = re.match(r"\s*Virtual Drive\s+(\d+):", line)
        if m:
            if current:
                vds.append(current)
            current = {"id": m.group(1)}
            continue
        if current:
            for key, field in [
                ("Name:", "name"),
                ("Size:", "size"),
                ("RAID Level:", "raid_level"),
                ("Boot Drive:", "boot_drive"),
                ("Physical Drives:", "physical_drives"),
                ("Health:", "health"),
                ("Status:", "status"),
            ]:
                if key in line:
                    current[field] = line.split(key, 1)[1].strip()
    if current:
        vds.append(current)
    return vds

def current_virtual_drives(cli: CimcCli, slot: str):
    cli.run("scope chassis")
    cli.run(f"scope storageadapter {slot}")
    detail = cli.run("show virtual-drive detail", timeout=120)
    return parse_virtual_drives(detail), detail

def create_virtual_drive(cli: CimcCli, slot: str, vd: dict):
    name = str(vd["name"])[:15]
    raid_level = map_raid_level(vd["raid_level"])
    disks = ",".join(normalize_disk_id(d) for d in vd["disks"])
    size_gb = vd.get("size_gb", 0)
    size_value = "" if int(size_gb) == 0 else f"{size_gb} GB"

    cli.run("scope chassis")
    cli.run(f"scope storageadapter {slot}")
    cli.child.sendline("create-virtual-drive")
    cli.child.expect(r"Please enter RAID level", timeout=30)
    cli.child.expect(r"--> ?", timeout=30)
    cli.child.sendline(raid_level)
    cli.child.expect(r"Enter comma-separated PDs from above list--> ?", timeout=60)
    cli.child.sendline(disks)
    cli.child.expect(r"Please enter Virtual Drive name.*--> ?", timeout=30)
    cli.child.sendline(name)
    cli.child.expect(r"Example format: '400 GB' --> ?", timeout=30)
    cli.child.sendline(size_value)
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline(strip_choice(int(vd.get("strip_size_kb", 64))))
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline("0")
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline(read_policy_choice(vd.get("read_policy", "read_ahead")))
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline(write_policy_choice(vd.get("write_policy", "write_back")))
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline("0")
    cli.child.expect(r"Choose number from above options or hit return to pick default--> ?", timeout=30)
    cli.child.sendline("0")
    idx = cli.child.expect([r"Enable SED security on virtual drive.*", r"OK\? \(y or n\)--> ?", PROMPT_RE], timeout=30)
    if idx == 0:
        cli.child.expect(r"Enter y or n--> ?", timeout=30)
        cli.child.sendline("n")
        cli.child.expect(r"OK\? \(y or n\)--> ?", timeout=30)
        cli.child.sendline("y")
    elif idx == 1:
        cli.child.sendline("y")
    cli.child.expect(PROMPT_RE, timeout=180)

def set_boot_virtual_drive(cli: CimcCli, slot: str, target_name: str):
    vds, _ = current_virtual_drives(cli, slot)
    matches = [vd for vd in vds if vd.get("name") == target_name]
    if not matches:
        raise RuntimeError(f"Could not find virtual drive named {target_name!r}")
    vd_id = matches[0]["id"]
    cli.run("scope chassis")
    cli.run(f"scope storageadapter {slot}")
    cli.run(f"scope virtual-drive {vd_id}")
    cli.child.sendline("set-boot-drive")
    cli.child.expect(r"Enter 'yes' to confirm -> ?", timeout=30)
    cli.child.sendline("yes")
    cli.child.expect(PROMPT_RE, timeout=60)

def ensure_boot_device(cli: CimcCli, device: dict):
    device_name = device["name"]
    device_type = device["type"]
    cli.run("scope bios")
    show_output = cli.run("show boot-device detail", timeout=60)
    if f"Boot Device {device_name}:" not in show_output:
        cli.run(f"create boot-device {device_name} {device_type}")
    cli.run(f"scope boot-device {device_name}")
    try:
        cli.run("set state Enabled")
    except Exception:
        cli.run("set status enabled")
    if "order" in device:
        cli.run(f"set order {device['order']}")
    if str(device_type).upper() == "PXE":
        if device.get("slot") is not None:
            cli.run(f"set slot {device['slot']}")
        if device.get("port") is not None:
            cli.run(f"set port {device['port']}")
    cli.child.sendline("commit")
    idx = cli.child.expect([r"Continue\?\[y\|N\]", r"Commiting device configuration", PROMPT_RE], timeout=60)
    if idx == 0:
        cli.child.sendline("y")
        cli.child.expect([r"Commiting device configuration", PROMPT_RE], timeout=60)
    cli.child.expect(PROMPT_RE, timeout=60)

def cmd_raid(host_cfg, vars_cfg):
    cli = CimcCli(host_cfg["cimc_ssh_host"], host_cfg["cimc_username"], host_cfg["cimc_password"], int(host_cfg.get("cimc_ssh_port", 22)), 120)
    cli.connect()
    try:
        slot = vars_cfg["raid_config"].get("controller_slot", "auto")
        if not slot or str(slot).lower() == "auto":
            slot = discover_storage_slot(cli)
        results = {"controller_slot": slot, "created": []}
        for vd in vars_cfg["raid_config"]["virtual_drives"]:
            create_virtual_drive(cli, slot, vd)
            results["created"].append(vd["name"])
        if vars_cfg["raid_config"].get("set_os_boot_drive", True):
            set_boot_virtual_drive(cli, slot, "OS_RAID1")
            results["boot_virtual_drive"] = "OS_RAID1"
        vds, _ = current_virtual_drives(cli, slot)
        results["virtual_drives"] = vds
        print(json.dumps(results, indent=2))
    finally:
        cli.close()

def cmd_raid_status(host_cfg, vars_cfg):
    cli = CimcCli(host_cfg["cimc_ssh_host"], host_cfg["cimc_username"], host_cfg["cimc_password"], int(host_cfg.get("cimc_ssh_port", 22)), 120)
    cli.connect()
    try:
        slot = vars_cfg["raid_config"].get("controller_slot", "auto")
        if not slot or str(slot).lower() == "auto":
            slot = discover_storage_slot(cli)
        vds, raw = current_virtual_drives(cli, slot)
        print(json.dumps({"controller_slot": slot, "virtual_drives": vds, "raw": raw}, indent=2))
    finally:
        cli.close()

def cmd_boot(host_cfg, vars_cfg):
    cli = CimcCli(host_cfg["cimc_ssh_host"], host_cfg["cimc_username"], host_cfg["cimc_password"], int(host_cfg.get("cimc_ssh_port", 22)), 120)
    cli.connect()
    try:
        results = {"configured_devices": []}
        for device in sorted(vars_cfg["boot_order"]["devices"], key=lambda x: int(x["order"])):
            ensure_boot_device(cli, device)
            results["configured_devices"].append(device["name"])
        cli.run("scope bios")
        results["show_boot_device_detail"] = cli.run("show boot-device detail", timeout=60)
        results["show_actual_boot_order"] = cli.run("show actual-boot-order", timeout=60)
        print(json.dumps(results, indent=2))
    finally:
        cli.close()

def main():
    parser = argparse.ArgumentParser(description="Cisco CIMC CLI automation helper")
    parser.add_argument("command", choices=["raid", "raid-status", "boot"])
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--vars", required=True, dest="vars_file")
    args = parser.parse_args()
    host_cfg, vars_cfg = load_config(Path(args.inventory), Path(args.vars_file))
    try:
        {"raid": cmd_raid, "raid-status": cmd_raid_status, "boot": cmd_boot}[args.command](host_cfg, vars_cfg)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
