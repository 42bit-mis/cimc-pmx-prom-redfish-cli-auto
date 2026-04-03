#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  ipmitool jq curl openssh-client sshpass

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

echo "Bootstrap completed."
echo "Activate the venv with: source .venv/bin/activate"
