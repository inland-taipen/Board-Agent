#!/usr/bin/env bash
# One-time server preparation for an Oracle Cloud Ubuntu instance.
#
# Run once, on the server, before the first deploy. Safe to run again - every
# step checks whether it has already been done.
#
#   bash server-setup.sh
#
# Handles the three things that catch people out on Oracle specifically:
#   1. Docker is not installed on their Ubuntu images.
#   2. Oracle's images ship an iptables ruleset that drops 80/443 even after
#      you open the ports in the console Security List. Both are required.
#   3. The smaller always-free shapes have 1 GB of RAM, which is not enough to
#      build the frontend - node runs out of memory. Swap fixes it.
set -euo pipefail

green() { printf '\033[32m%s\033[0m\n' "$1"; }
info()  { printf '\033[36m==> %s\033[0m\n' "$1"; }

info "1/4  Docker"
if command -v docker >/dev/null 2>&1; then
    green "     already installed ($(docker --version))"
else
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    green "     installed"
    NEED_RELOGIN=1
fi

info "2/4  Firewall (ports 80 and 443)"
# Oracle's Ubuntu image has a REJECT rule near the end of the INPUT chain, so
# new rules must be inserted above it rather than appended.
for port in 80 443; do
    if sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
        green "     port $port already open"
    else
        sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport "$port" -j ACCEPT
        green "     opened port $port"
    fi
done
if ! dpkg -s iptables-persistent >/dev/null 2>&1; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq iptables-persistent
fi
sudo netfilter-persistent save >/dev/null
green "     rules saved (they survive reboot)"

info "3/4  Swap"
TOTAL_MB=$(free -m | awk '/^Mem:/{print $2}')
SWAP_MB=$(free -m | awk '/^Swap:/{print $2}')
if [ "$SWAP_MB" -gt 0 ]; then
    green "     ${SWAP_MB}MB already configured"
elif [ "$TOTAL_MB" -lt 4000 ]; then
    # Building the frontend needs more headroom than a 1GB shape provides.
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    green "     added 2GB swap (RAM is ${TOTAL_MB}MB; the build needs the headroom)"
else
    green "     not needed (${TOTAL_MB}MB RAM)"
fi

info "4/4  Unpack the application"
if [ -f ~/boardlens-deploy.tar.gz ]; then
    mkdir -p ~/BoardAgent
    tar xzf ~/boardlens-deploy.tar.gz -C ~/BoardAgent
    green "     unpacked to ~/BoardAgent"
else
    echo "     ~/boardlens-deploy.tar.gz not found."
    echo "     Copy it up first, from your laptop:"
    echo "       bash deploy/package.sh"
    echo "       scp -i <key> /tmp/boardlens-deploy.tar.gz ubuntu@<SERVER_IP>:~/"
    exit 1
fi

echo
green "Server ready."
echo
if [ "${NEED_RELOGIN:-0}" = "1" ]; then
    echo "IMPORTANT: log out and back in before continuing, so your user picks up"
    echo "the docker group:    exit    then ssh back in"
    echo
fi
echo "Next:"
echo "  cd ~/BoardAgent/deploy"
echo "  cp .env.prod.example .env"
echo "  nano .env                      # fill in the six values"
echo "  bash start.sh"
