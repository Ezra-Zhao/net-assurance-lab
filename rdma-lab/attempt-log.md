# Attempt Log — Module B RDMA (Soft-RoCE / rxe)

Date: 2026-10-22 (probe window 22:02–22:05 UTC)
Host: `htch-runtime` — Ubuntu 24.04.5 LTS, kernel `7.0.0-39-generic` x86_64, running as root in a managed VM / container-like runtime
Goal: bring up a Soft-RoCE (`rxe`) device and run a minimal RDMA benchmark (`ib_send_bw` / `ib_write_bw`).
Outcome: **FAILED at the kernel layer — no RDMA transfer was run, no number was measured.**
This log is the verbatim record: every command, its raw output, and its exit code, in the order run. Nothing below was edited, summarised, or re-typed.

## Verdict in one paragraph

The host kernel was built without InfiniBand/RDMA support and the runtime exposes no kernel-module tree at all, so there is no path from inside this environment to an RDMA device: `/proc/config.gz` states `# CONFIG_INFINIBAND is not set`; `/lib/modules` and `/proc/modules` do not exist; `modprobe rdma_rxe` fails with `Module rdma_rxe not found in directory /lib/modules/7.0.0-39-generic`; `rdma link` fails with `Failed to open NETLINK_RDMA socket`. Installing the full userspace stack (round 3: `rdma-core 50.0-2ubuntu0.2`, `ibverbs-utils`, `perftest 24.01.0`) succeeds, and the tools then fail cleanly at device discovery — `ibv_devices`: `Failed to get IB devices list: Function not implemented`; `ib_send_bw -d rxe0`: `Did not detect devices` / `Unable to find the Infiniband/RoCE device`. The blocker is the host kernel, not configuration, not permissions (the probe ran as root), and not missing packages.

## Failure chain (each link points at the round that proves it)

1. No RDMA sysfs: `/sys/class/infiniband` does not exist; `/sys/module` does not exist. (Round 1)
2. No module tree: `/lib/modules` does not exist; `/proc/modules` does not exist; `lsmod` errors with `could not open /proc/modules: No such file or directory`. (Round 1)
3. Modules cannot be loaded: `modprobe rdma_rxe` / `ib_uverbs` / `siw` / `rdma_cm` / `ib_cm` all return `FATAL: Module ... not found in directory /lib/modules/7.0.0-39-generic`; `modinfo rdma_rxe` returns `Module rdma_rxe not found.` (Rounds 1–2)
4. Root cause in the kernel config: `zcat /proc/config.gz` shows `# CONFIG_INFINIBAND is not set` (only `CONFIG_CGROUP_RDMA=y` is present). A raw NETLINK_RDMA socket from Python fails with `OSError: [Errno 93] Protocol not supported`. (Round 2)
5. Userspace is not the blocker: before `apt-get update`, the package cache was stale and `apt-get install --dry-run` reported `Unable to locate package rdma-core`; after `apt-get update`, `rdma-core`, `ibverbs-utils`, `ibverbs-providers`, and `perftest` install cleanly and the binaries land in `/usr/bin`. (Rounds 2–3)
6. With tools installed, device discovery still fails: `ibv_devices` and `ibv_devinfo` return `Failed to get IB devices list: Function not implemented`; `rdma link add rxe0 type rxe netdev lo` still returns `Failed to open NETLINK_RDMA socket`; `/dev/infiniband` does not exist. (Round 3)

## What was NOT done

- No `ib_send_bw` / `ib_write_bw` / `ib_send_lat` client-server run completed, so there is no `results.md` in this folder and no latency or bandwidth figure anywhere in this module. Any number would be invented.
- No workaround was faked: no userspace RDMA emulation, no TCP result relabelled as RDMA, no borrowed benchmark output from another machine.
- The apt installs in round 3 changed only this disposable build VM's userspace (four packages plus dependencies). No existing file in `net-assurance-lab` was modified by the attempts.

## How this gets unblocked

Any host where the kernel ships the RDMA stack and the operator may load modules: bare metal, a self-managed VM (e.g. a cloud instance with the stock Ubuntu kernel, where `linux-modules-extra` provides `rdma_rxe`), or a home-lab box. The full procedure is in `README.md` sections 3–5; the pass gate is `ibv_devices` listing `rxe0` with port state `PORT_ACTIVE`.

---

## Round 1 — Environment and kernel-stack probe (2026-10-22T22:02:16Z)

Probe started: 2026-10-22T22:02:16Z / 2026-10-22 22:02:16 UTC
Host: htch-runtime

### $ uname -a
```
Linux htch-runtime 7.0.0-39-generic #1 SMP PREEMPT_DYNAMIC Thu Sep 24 08:42:15 UTC 2026 x86_64 x86_64 x86_64 GNU/Linux
[exit code: 0]
```

### $ cat /etc/os-release
```
PRETTY_NAME="Ubuntu 24.04.5 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.5 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
HOME_URL="https://www.ubuntu.com/"
SUPPORT_URL="https://help.ubuntu.com/"
BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"
PRIVACY_POLICY_URL="https://www.ubuntu.com/legal/terms-and-policies/privacy-policy"
UBUNTU_CODENAME=noble
LOGO=ubuntu-logo
IMAGE_ID="hatch-image"
IMAGE_VERSION="0.1.46"
[exit code: 0]
```

### $ id
```
uid=0(root) gid=0(root) groups=0(root)
[exit code: 0]
```

### $ ls -la /sys/class/infiniband 2>&1; ls -la /sys/class/ 2>&1 | head -60
```
ls: cannot access '/sys/class/infiniband': No such file or directory
total 0
drwxr-xr-x 67 nobody nogroup   0 Oct 22 22:02 .
dr-xr-xr-x  9 root   root    180 Oct 22 20:43 ..
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 accel
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ata_device
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ata_link
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ata_port
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 backlight
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 bdi
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 block
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 bsg
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 devcoredump
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 devfreq
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 devfreq-event
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 devlink
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 dma
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 dma_heap
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 dmi
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 drm
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 extcon
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 firmware
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 gpio
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 graphics
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 hwmon
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 i2c-dev
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ieee80211
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 input
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 intel_scu_ipc
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 iommu
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 leds
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 mdio_bus
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 mem
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 misc
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 mmc_host
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 nd
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 net
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 pci_bus
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 pci_epc
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 phy
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 power_supply
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 powercap
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ppp
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 pps
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 ptp
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 pwm
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 rapidio_port
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 regulator
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 remoteproc
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 rfkill
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 rtc
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 scsi_device
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 scsi_disk
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 scsi_generic
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 scsi_host
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 spi_master
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 spi_slave
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 thermal
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 tpm
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 tpmrm
drwxr-xr-x  2 nobody nogroup   0 Oct 22 22:02 tsm
[exit code: 0]
```

### $ ls /lib/modules/$(uname -r)/kernel/drivers/infiniband/ 2>&1; find /lib/modules -name '*rxe*' -o -name '*rdma*' 2>&1 | head -40
```
ls: cannot access '/lib/modules/7.0.0-39-generic/kernel/drivers/infiniband/': No such file or directory
find: '/lib/modules': No such file or directory
[exit code: 0]
```

### $ lsmod
```
libkmod: ERROR ../libkmod/libkmod-module.c:1762 kmod_module_new_from_loaded: could not open /proc/modules: No such file or directory
Error: could not get list of modules: No such file or directory
[exit code: 1]
```

### $ cat /proc/modules
```
cat: /proc/modules: No such file or directory
[exit code: 1]
```

### $ ls /proc/modules 2>&1; ls -la /proc/ | head -20
```
ls: cannot access '/proc/modules': No such file or directory
total 0
dr-xr-xr-x 283 nobody nogroup                 0 Oct 22 20:43 .
drwxr-xr-x   1 root   root                   32 Jan  1  1970 ..
dr-xr-xr-x   9 root   root                    0 Oct 22 20:43 1
dr-xr-xr-x   9 root   root                    0 Oct 22 21:58 10072
dr-xr-xr-x   9 root   root                    0 Oct 22 21:58 10073
dr-xr-xr-x   9 root   root                    0 Oct 22 21:58 11748
dr-xr-xr-x   9 root   root                    0 Oct 22 22:00 12866
dr-xr-xr-x   9 root   root                    0 Oct 22 22:00 12868
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 12870
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 12963
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 13014
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 13015
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 13036
dr-xr-xr-x   9 root   root                    0 Oct 22 22:01 13037
dr-xr-xr-x   9 root   root                    0 Oct 22 22:02 13112
dr-xr-xr-x   9 root   root                    0 Oct 22 22:02 13182
dr-xr-xr-x   9 root   root                    0 Oct 22 22:02 13190
dr-xr-xr-x   9 root   root                    0 Oct 22 22:02 13194
dr-xr-xr-x   9 root   root                    0 Oct 22 22:02 13198
[exit code: 0]
```

### $ modinfo rdma_rxe
```
modinfo: ERROR: Module rdma_rxe not found.
[exit code: 1]
```

### $ modinfo ib_core
```
modinfo: ERROR: Module ib_core not found.
[exit code: 1]
```

### $ modprobe rdma_rxe
```
modprobe: FATAL: Module rdma_rxe not found in directory /lib/modules/7.0.0-39-generic
[exit code: 1]
```

### $ modprobe ib_uverbs
```
modprobe: FATAL: Module ib_uverbs not found in directory /lib/modules/7.0.0-39-generic
[exit code: 1]
```

### $ modprobe -v rdma_rxe 2>&1; echo ---; dmesg 2>&1 | tail -20
```
modprobe: FATAL: Module rdma_rxe not found in directory /lib/modules/7.0.0-39-generic
---
dmesg: read kernel buffer failed: Operation not permitted
[exit code: 0]
```

### $ which ibv_devices
```
[exit code: 1]
```

### $ which ibv_devinfo
```
[exit code: 1]
```

### $ which rdma
```
/usr/bin/rdma
[exit code: 0]
```

### $ which rxe_cfg
```
[exit code: 1]
```

### $ which ib_send_bw
```
[exit code: 1]
```

### $ which ib_write_bw
```
[exit code: 1]
```

### $ which ib_send_lat
```
[exit code: 1]
```

### $ rdma link
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ rdma link show
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ rdma dev
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ rdma dev show
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ ibv_devices 2>&1; ibv_devinfo 2>&1
```
bash: line 1: ibv_devices: command not found
bash: line 1: ibv_devinfo: command not found
[exit code: 127]
```

### $ ip -br link 2>&1; ip -br addr 2>&1
```
lo               UNKNOWN        00:00:00:00:00:00 <LOOPBACK,UP,LOWER_UP> 
host0@if3        UP             72:dc:7c:34:2f:fd <BROADCAST,MULTICAST,UP,LOWER_UP> 
lo               UNKNOWN        127.0.0.1/8 ::1/128 
host0@if3        UP             198.19.0.2/30 fd8b:4f84:7d32:99::2/64 fe80::70dc:7cff:fe34:2ffd/64 
[exit code: 0]
```

### $ ls -la /dev/infiniband/ 2>&1; ls /dev/*uverbs* /dev/*rdma* 2>&1
```
ls: cannot access '/dev/infiniband/': No such file or directory
ls: cannot access '/dev/*uverbs*': No such file or directory
ls: cannot access '/dev/*rdma*': No such file or directory
[exit code: 2]
```

### $ dpkg -l 2>&1 | grep -iE 'ibverbs|rdma|perftest|rxe' ; echo ---apt-cache---; apt-cache policy libibverbs1 ibverbs-providers rdma-core perftest 2>&1 | head -60
```
---apt-cache---
[exit code: 0]
```

### $ capsh --print 2>&1 | head -40; cat /proc/self/status | grep -i cap
```
Current: =ep cap_sys_ptrace-ep
Bounding set =cap_chown,cap_dac_override,cap_dac_read_search,cap_fowner,cap_fsetid,cap_kill,cap_setgid,cap_setuid,cap_setpcap,cap_linux_immutable,cap_net_bind_service,cap_net_broadcast,cap_net_admin,cap_net_raw,cap_ipc_lock,cap_ipc_owner,cap_sys_module,cap_sys_rawio,cap_sys_chroot,cap_sys_pacct,cap_sys_admin,cap_sys_boot,cap_sys_nice,cap_sys_resource,cap_sys_time,cap_sys_tty_config,cap_mknod,cap_lease,cap_audit_write,cap_audit_control,cap_setfcap,cap_mac_override,cap_mac_admin,cap_syslog,cap_wake_alarm,cap_block_suspend,cap_audit_read,cap_perfmon,cap_bpf,cap_checkpoint_restore
Ambient set =
Current IAB: !cap_sys_ptrace
Securebits: 00/0x0/1'b0 (no-new-privs=1)
 secure-noroot: no (unlocked)
 secure-no-suid-fixup: no (unlocked)
 secure-keep-caps: no (unlocked)
 secure-no-ambient-raise: no (unlocked)
uid=0(root) euid=0(root)
gid=0(root)
groups=
Guessed mode: HYBRID (4)
CapInh:	0000000000000000
CapPrm:	000001fffff7ffff
CapEff:	000001fffff7ffff
CapBnd:	000001fffff7ffff
CapAmb:	0000000000000000
[exit code: 0]
```

### $ ls -la /sys/module/ 2>&1 | head -40
```
ls: cannot access '/sys/module/': No such file or directory
[exit code: 0]
```

### $ apt-get install -y --dry-run rdma-core ibverbs-utils perftest 2>&1 | tail -30
```
Reading package lists...
Building dependency tree...
E: Unable to locate package rdma-core
E: Unable to locate package ibverbs-utils
E: Unable to locate package perftest
[exit code: 0]
```

Probe finished: 2026-10-22T22:02:18Z

---

## Round 2 — Device-creation attempts, alternative drivers, kernel config (2026-10-22T22:02:29Z)

Notes: `rdma link add` was attempted for both rxe (Soft-RoCE) and siw (Soft-iWARP); both fail at the same NETLINK_RDMA socket, before any driver logic runs. The `apt-get update` in this round refreshed a stale package cache (70.5 MB fetched) — compare round 1's dry-run (`Unable to locate package`) with round 3's successful install.

Second-round attempts: 2026-10-22T22:02:29Z

### $ rdma link add rxe0 type rxe netdev lo 2>&1
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ rdma link add siw0 type siw netdev lo 2>&1
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ modprobe siw 2>&1; modprobe rdma_cm 2>&1; modprobe ib_cm 2>&1
```
modprobe: FATAL: Module siw not found in directory /lib/modules/7.0.0-39-generic
modprobe: FATAL: Module rdma_cm not found in directory /lib/modules/7.0.0-39-generic
modprobe: FATAL: Module ib_cm not found in directory /lib/modules/7.0.0-39-generic
[exit code: 1]
```

### $ ls /usr/include/infiniband/ 2>&1 | head -20; ls /usr/lib/x86_64-linux-gnu/libibverbs* 2>&1; ldconfig -p 2>&1 | grep -iE 'ibverbs|rdmacm'
```
ls: cannot access '/usr/include/infiniband/': No such file or directory
ls: cannot access '/usr/lib/x86_64-linux-gnu/libibverbs*': No such file or directory
[exit code: 1]
```

### $ cat /proc/cmdline 2>&1; ls /boot/ 2>&1 | head; zcat /proc/config.gz 2>&1 | grep -iE 'INFINIBAND|RDMA|RXE|SIW' | head -20; ls /usr/src/ 2>&1
```
console=ttyS0 root=/dev/vda rootfstype=btrfs ip=dhcp ds=nocloud;s=http://169.254.169.254/latest/ lsm=landlock,lockdown,yama,integrity,apparmor,bpf ro systemd.set_credential=vmm.notify_socket:vsock-stream:2:512
loader
CONFIG_CGROUP_RDMA=y
# CONFIG_INFINIBAND is not set
python3.12
[exit code: 0]
```

### $ apt-get update 2>&1 | tail -5; apt-cache search rdma 2>&1 | head -20
```
Get:70 http://azure.archive.ubuntu.com/ubuntu noble-security/universe Translation-en [246 kB]
Get:71 http://azure.archive.ubuntu.com/ubuntu noble-security/multiverse amd64 Packages [45.4 kB]
Get:72 http://azure.archive.ubuntu.com/ubuntu noble-security/multiverse Translation-en [12.1 kB]
Fetched 70.5 MB in 47s (1503 kB/s)
Reading package lists...
libibverbs-dev - Development files for the libibverbs library
libibverbs1 - Library for direct userspace use of RDMA (InfiniBand/iWARP)
librdmacm-dev - Development files for the librdmacm library
librdmacm1t64 - Library for managing RDMA connections
dapl2-utils - utilities for use with the DAPL libraries
glusterfs-cli - clustered file-system (cli package)
glusterfs-client - clustered file-system (client package)
glusterfs-common - GlusterFS common libraries and translator modules
glusterfs-server - clustered file-system (server package)
ibacm - InfiniBand Communication Manager Assistant (ACM)
ibverbs-utils - Examples for the libibverbs library
ksmbd-tools - cifsd kernel server userspace utilities
libdapl-dev - development files for the DAPL libraries
libdapl2 - Direct Access Programming Library (DAPL)
libgfapi0 - GlusterFS gfapi shared library
libgfchangelog0 - GlusterFS gfchangelog shared library
libgfrpc0 - GlusterFS libgfrpc shared library
libgfxdr0 - GlusterFS libgfxdr shared library
libglusterfs-dev - Development files for GlusterFS libraries
libglusterfs0 - GlusterFS shared library
[exit code: 0]
```

### $ python3 -c 'import socket; s=socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, 20); print(s)' 2>&1
```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/usr/lib/python3.12/socket.py", line 233, in __init__
    _socket.socket.__init__(self, family, type, proto, fileno)
OSError: [Errno 93] Protocol not supported
[exit code: 1]
```

Second-round finished: 2026-10-22T22:03:25Z

---

## Round 3 — Userspace installed, benchmark attempted, still no device (2026-10-22T22:04:11Z)

Notes: this round removes "missing tools" as an explanation. With `ibv_devices`, `ibv_devinfo`, `ib_send_bw`, `ib_write_bw`, and `ib_send_lat` all present in `/usr/bin`, every RDMA operation still fails at device discovery because the kernel has no RDMA subsystem to answer it. The perftest line `WARNING: BW peak won't be measured in this run.` is the tool's own wording; no bandwidth was measured.

Third-round attempts (userspace install + retry): 2026-10-22T22:04:11Z

### $ DEBIAN_FRONTEND=noninteractive apt-get install -y rdma-core ibverbs-utils ibverbs-providers perftest 2>&1 | tail -25
```
Selecting previously unselected package ibverbs-utils.
Preparing to unpack .../09-ibverbs-utils_50.0-2ubuntu0.2_amd64.deb ...
Unpacking ibverbs-utils (50.0-2ubuntu0.2) ...
Selecting previously unselected package libibumad3:amd64.
Preparing to unpack .../10-libibumad3_50.0-2ubuntu0.2_amd64.deb ...
Unpacking libibumad3:amd64 (50.0-2ubuntu0.2) ...
Selecting previously unselected package perftest.
Preparing to unpack .../11-perftest_24.01.0+0.38-1build2_amd64.deb ...
Unpacking perftest (24.01.0+0.38-1build2) ...
Setting up pci.ids (0.0~2024.03.31-1ubuntu0.1) ...
Setting up libibumad3:amd64 (50.0-2ubuntu0.2) ...
Setting up libpci3:amd64 (1:3.10.0-2build1) ...
Setting up libnl-3-200:amd64 (3.7.0-0.3build1.1) ...
Setting up rdma-core (50.0-2ubuntu0.2) ...
invoke-rc.d: policy-rc.d denied execution of start.
/usr/sbin/policy-rc.d returned 101, not running 'start iwpmd.service rdma-hw.target rdma-ndd.service'
host0: Failed to write 'change' to '/sys/devices/virtual/net/host0/uevent': Read-only file system

Setting up dmidecode (3.5-3ubuntu0.2) ...
Setting up libnl-route-3-200:amd64 (3.7.0-0.3build1.1) ...
Setting up libibverbs1:amd64 (50.0-2ubuntu0.2) ...
Setting up ibverbs-providers:amd64 (50.0-2ubuntu0.2) ...
Setting up ibverbs-utils (50.0-2ubuntu0.2) ...
Setting up librdmacm1t64:amd64 (50.0-2ubuntu0.2) ...
Setting up perftest (24.01.0+0.38-1build2) ...
Processing triggers for libc-bin (2.39-0ubuntu8.9) ...
[exit code: 0]
```

### $ which ibv_devices ibv_devinfo ib_send_bw ib_write_bw ib_send_lat rxe_cfg 2>&1; dpkg -l rdma-core ibverbs-utils perftest 2>&1 | tail -6
```
/usr/bin/ibv_devices
/usr/bin/ibv_devinfo
/usr/bin/ib_send_bw
/usr/bin/ib_write_bw
/usr/bin/ib_send_lat
|/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
||/ Name           Version              Architecture Description
+++-==============-====================-============-====================================================
ii  ibverbs-utils  50.0-2ubuntu0.2      amd64        Examples for the libibverbs library
ii  perftest       24.01.0+0.38-1build2 amd64        Infiniband verbs performance tests
ii  rdma-core      50.0-2ubuntu0.2      amd64        RDMA core userspace infrastructure and documentation
[exit code: 0]
```

### $ ibv_devices 2>&1
```
Failed to get IB devices list: Function not implemented
[exit code: 1]
```

### $ ibv_devinfo 2>&1
```
Failed to get IB devices list: Function not implemented
[exit code: 255]
```

### $ rdma link show 2>&1; rdma dev show 2>&1
```
Failed to open NETLINK_RDMA socket
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ rdma link add rxe0 type rxe netdev lo 2>&1
```
Failed to open NETLINK_RDMA socket
[exit code: 1]
```

### $ ib_send_bw -d rxe0 2>&1 | head -10
```
 Did not detect devices 
 If device exists, check if driver is up
 Unable to find the Infiniband/RoCE device
 WARNING: BW peak won't be measured in this run.
[exit code: 0]
```

### $ ls /sys/class/infiniband 2>&1; ls /dev/infiniband 2>&1
```
ls: cannot access '/sys/class/infiniband': No such file or directory
ls: cannot access '/dev/infiniband': No such file or directory
[exit code: 2]
```

Third-round finished: 2026-10-22T22:05:01Z
