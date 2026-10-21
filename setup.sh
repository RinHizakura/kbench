#!/bin/sh -e
# Install kbench dependencies: fio/sysbench (apt), schbench and rtla (built from source).

sudo apt-get update
sudo apt-get install -y fio sysbench iperf3 stress-ng build-essential git \
    pkg-config libtracefs-dev libtraceevent-dev
sudo apt-get install -y linux-tools-common "linux-tools-$(uname -r)" \
    || echo "no linux-tools for this kernel; perf bench will be skipped"

if command -v schbench >/dev/null; then
    echo "schbench already installed"
else
    tmp=$(mktemp -d)
    git clone --depth 1 https://git.kernel.org/pub/scm/linux/kernel/git/mason/schbench.git "$tmp"
    make -C "$tmp"
    sudo install "$tmp/schbench" /usr/local/bin/
    rm -rf "$tmp"
fi

# rtla from the kernel tree (only the tools/ bits it needs; it talks to tracefs, so
# it does not have to match the running kernel). Ubuntu's /usr/bin/rtla is a wrapper
# that only knows the stock kernel's binary, so install ahead of it.
if [ -x /usr/local/bin/rtla ]; then
    echo "rtla already installed"
else
    tmp=$(mktemp -d)
    git clone --depth 1 --filter=blob:none --sparse \
        https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git "$tmp"
    git -C "$tmp" sparse-checkout set tools/scripts tools/build tools/include \
        tools/lib/subcmd tools/lib/ctype.c tools/lib/string.c tools/lib/str_error_r.c \
        tools/tracing/rtla
    make -C "$tmp/tools/tracing/rtla" VERSION=git BUILD_BPF_SKEL=0
    sudo install "$tmp/tools/tracing/rtla/rtla" /usr/local/bin/
    rm -rf "$tmp"
fi

echo "setup done:"
