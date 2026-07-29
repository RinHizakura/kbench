#!/bin/sh -e
# Install kbench dependencies: fio/sysbench/rtla (apt) and schbench (built from source).

sudo apt-get update
sudo apt-get install -y fio sysbench iperf3 build-essential git
sudo apt-get install -y rtla || echo "no rtla package; try linux-tools-$(uname -r)"

if command -v schbench >/dev/null; then
    echo "schbench already installed"
else
    tmp=$(mktemp -d)
    git clone --depth 1 https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git "$tmp"
    make -C "$tmp"
    sudo install "$tmp/schbench" /usr/local/bin/
    rm -rf "$tmp"
fi

echo "setup done:"
fio --version
schbench --help
