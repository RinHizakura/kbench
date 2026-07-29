#!/bin/sh -e
# Install kbench dependencies: fio (apt) and schbench (built from source).

sudo apt-get update
sudo apt-get install -y fio build-essential git

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
