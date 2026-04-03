# CIMC AUTO RAID CREATION ( read _HISTORY ) for Cisco UCS C220 M4

This package is rebuilt for your standalone **Cisco UCS C220 M4** with **CIMC 4.1(2m)**.

## Why this layout changed

The old package used UCS Manager-style Ansible modules and CIMC XML API.
That was the wrong fit for a standalone M4.

This package uses:

- **Redfish / REST** for baseline + verification
- **CIMC CLI over SSH** for RAID + persistent boot order

That split is deliberate:

- Cisco documents Redfish at `https://<cimc>/redfish/v1/` for C-Series CIMC.
- Cisco's 4.1 Redfish guide explicitly says **virtual-drive creation is not supported**
  on **C220 M4 / C240 M4 / C460 M4** through Redfish.
- Cisco's CLI guide documents storage virtual-drive creation and persistent BIOS boot-order control.

## Final tree

```text
cimc-automation-redfish-cli/
├── ansible.cfg
├── inventory.yml
├── cimc_vars.yml
├── requirements.txt
├── README.md
├── playbooks/
│   ├── 01_cimc_baseline.yml
│   ├── 02_cimc_raid_config.yml
│   ├── 03_cimc_boot_order.yml
│   └── 04_cimc_verify.yml
├── templates/
│   └── verification_report.md.j2
└── scripts/
    ├── bootstrap_ubuntu24.sh
    ├── cimc_cli.py
    └── cimc_ipmi_setup.sh
```

## First run

```bash
unzip cimc-automation-redfish-cli.zip
cd cimc-automation-redfish-cli
chmod +x scripts/bootstrap_ubuntu24.sh scripts/cimc_ipmi_setup.sh scripts/cimc_cli.py
./scripts/bootstrap_ubuntu24.sh
source .venv/bin/activate
```

Edit:
- `inventory.yml`
- `cimc_vars.yml`

Then run:
```bash
ansible-playbook playbooks/01_cimc_baseline.yml
ansible-playbook playbooks/04_cimc_verify.yml
```

Only after review should you enable and run the destructive playbooks:
```bash
# in cimc_vars.yml:
# raid_config.apply: true
# boot_order.apply: true

ansible-playbook playbooks/02_cimc_raid_config.yml
ansible-playbook playbooks/03_cimc_boot_order.yml
```

## Important notes

### RAID automation on C220 M4
For your platform, this package uses **CIMC CLI** and not Redfish to create virtual drives.

### `size_gb: 0`
For RAID creation, `size_gb: 0` is treated as "use the controller's default / maximum available size".
If your controller refuses a blank size prompt, replace `0` with an explicit value.

### PXE slot / port
For persistent PXE boot order, CIMC CLI precision boot devices need a slot and port.
The sample config assumes onboard LOM port 1:
```yaml
slot: L
port: 1
```
Adjust if your boot NIC is different.

### Network changes can disconnect you
`cimc_network.apply` defaults to `false` because changing the CIMC IP or hostname can interrupt the current session.
