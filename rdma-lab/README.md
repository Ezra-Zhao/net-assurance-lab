# Module B — RDMA Concept Lab (Soft-RoCE / rxe)

> **Status: DOCUMENT-LEVEL ONLY — NOT MEASURED.**
> This module was designed and attempted on 2026-10-22, but no RDMA
> transfer was run and no latency / bandwidth number in this folder was
> measured. The build VM has no RDMA kernel stack (no `/lib/modules`,
> no `/proc/modules`, no `/sys/class/infiniband`, NETLINK_RDMA fails),
> so `rdma_rxe` cannot be loaded there. Full verbatim evidence is in
> [`attempt-log.md`](attempt-log.md). Do not cite this module as a
> completed RDMA benchmark. On a host that can load `rdma_rxe` (bare
> metal or a VM with module access), the steps below are the exact
> procedure to turn it into a measured result.

Proof context: Module B of `net-assurance-lab`, built for the Atoms —
Staff HPC Network Engineer role gap: data-centre / physical-layer
networking and Prometheus experience exist (Module A), but InfiniBand /
RDMA / RoCE cluster networking has no prior hands-on history. This lab
is the smallest honest bridge: run real RDMA verbs over a software
RoCE device, read the counters, and learn the failure vocabulary —
not a claim of production HPC experience.

---

## 1. What this experiment is meant to prove (and not prove)

Meant to prove, once run on a capable host:

- I can bring up a Soft-RoCE (rxe) device on a plain Ethernet
  interface, verify it with `ibv_devices` / `ibv_devinfo`, and explain
  each step.
- I can run a client/server RDMA benchmark (`ib_send_bw`,
  `ib_write_bw`, `ib_send_lat`) between two endpoints, read bandwidth
  and latency correctly, and vary message size / queue depth on
  purpose.
- I can troubleshoot the common bring-up failures (device not ACTIVE,
  GID / RoCE version mismatch, MTU mismatch, QP stuck in non-RTS
  state) from tool output instead of guessing.

Not claimed, even after a successful run:

- No InfiniBand fabric experience: no subnet manager, no LID / P_Key,
  no real HCA, no lossless fabric tuning.
- No production throughput claim: Soft-RoCE numbers on loopback or
  1/10 GbE say nothing about NDR 400 Gb/s fabric performance.
- No GPU / collective experience: no NCCL, no GPUDirect RDMA, no
  multi-node scaling result.

## 2. Topology

Minimal, two-endpoint, reproducible on one or two hosts:

```
Option 1 — single host, loopback-style (bring-up smoke test)
  Host A: rxe0 on lo  ---- RDMA_CM over 127.0.0.1 ---- rxe0 (same device)
          server: ib_send_bw -d rxe0 -x 0
          client: ib_send_bw -d rxe0 -x 0 127.0.0.1
  Use: proves the verbs stack works at all. Bandwidth/latency here
  measure the host kernel + CPU, not any wire. Label results as such.

Option 2 — two hosts / two VMs, one Ethernet link (preferred)
  Host A (server)  eth0 10.10.0.1/24 ── direct cable or one switch ── eth0 10.10.0.2/24  Host B (client)
                   rxe0 on eth0                                          rxe0 on eth0
  Use: first numbers that involve a real NIC queue and a real wire.
  Still RoCE over software — CPU does the work an HCA would offload.
```

Both hosts: Ubuntu 24.04 (or any distro with kernel >= 5.x and the
`rdma-core` userspace), same MTU on both ends (start at 1500; try
9000 only after the 1500 run passes, and change both ends together).

## 3. Prerequisites — check these before blaming RDMA

```bash
uname -r
lsmod | grep -E 'rdma_rxe|ib_core|ib_uverbs'   # or: cat /proc/modules
ls /sys/class/infiniband/                       # expect: rxe0 after setup
ip -br link                                     # note the netdev for rxe
```

If `/lib/modules/$(uname -r)` does not exist, or `modprobe` answers
`Module rdma_rxe not found`, or `rdma link` answers
`Failed to open NETLINK_RDMA socket` — stop. That is a host/kernel
problem, not an RDMA configuration problem. That is exactly what
happened on the 2026-10-22 build VM; see `attempt-log.md`.

Install userspace on a capable host (Debian/Ubuntu names):

```bash
sudo apt-get update
sudo apt-get install -y rdma-core ibverbs-utils ibverbs-providers \
                        libibverbs-dev perftest iputils-ping
```

Package names vary by distro (RHEL family: `rdma-core`, `libibverbs`,
`perftest`). Verify after install: `which ibv_devices ib_send_bw rdma`.

## 4. Soft-RoCE bring-up steps (per host)

```bash
# 1. Load the stack
sudo modprobe ib_core
sudo modprobe ib_uverbs
sudo modprobe rdma_rxe            # provides the rxe software driver
#    Soft-iWARP alternative: sudo modprobe siw

# 2. Create the rxe device on a real netdev (use eth0 in Option 2;
#    lo only for the Option 1 smoke test)
sudo rdma link add rxe0 type rxe netdev eth0
#    Legacy tool, if present: sudo rxe_cfg start eth0

# 3. Verify — all three must agree before running any benchmark
rdma link show                    # rxe0: state ACTIVE, physical_state LINK_UP
ibv_devices                       # expect a row: rxe0
ibv_devinfo -d rxe0               # state: PORT_ACTIVE, link_layer: Ethernet
                                  # note max_mtu / active_mtu and the GID table

# 4. Reachability at IP layer first (RDMA-CM rides on it)
ping -c 3 10.10.0.1               # from the peer; fix IP before touching QP state
```

Pass criteria to write down before benchmarking: device name, port
state `PORT_ACTIVE`, link layer `Ethernet` (that is what makes it
RoCE, not native IB), RoCE version / GID index to be used (`-x`
flag below), and the MTU in force on both ends.

## 5. Benchmark runs — commands and how to read them

Server on Host A, client on Host B (swap roles and re-run; asymmetry
is itself a finding). Keep the exact command line with every result.

```bash
# Bandwidth, SEND verb (two-sided)
#   server:
ib_send_bw -d rxe0 -x 0 -F --report_gbits
#   client:
ib_send_bw -d rxe0 -x 0 -F --report_gbits 10.10.0.1

# Bandwidth, RDMA WRITE (one-sided — the HPC/AI-training pattern)
ib_write_bw -d rxe0 -x 0 -F --report_gbits            # server
ib_write_bw -d rxe0 -x 0 -F --report_gbits 10.10.0.1  # client

# Latency, SEND verb
ib_send_lat -d rxe0 -x 0 -F            # server
ib_send_lat -d rxe0 -x 0 -F 10.10.0.1  # client

# Size / depth sweep (repeat per setting, one variable at a time)
ib_send_bw -d rxe0 -x 0 -F --report_gbits -s 65536 -q 4 10.10.0.1
```

Flags used: `-d` device, `-x` GID index (must match the RoCE version
in use — RoCEv2 is the default expectation on routed Ethernet; a
wrong index is the classic "it connects on one host pair and not
another" bug), `-F` fail on invalid arguments instead of silently
defaulting, `--report_gbits` so the unit is explicit in the output.

How to read perftest output:

- `BW average [Gb/sec]` — the headline bandwidth for that message
  size. Expect it to rise with message size and plateau; a flat low
  line at every size usually means CPU saturation (expected with
  Soft-RoCE — note host CPU during the run) or a 1 GbE bottleneck.
- `MsgRate [Mpps]` — messages per second; the small-message story.
  Small messages are rate-bound, large messages are byte-bound.
- Latency runs report min / max / mean / stdev and percentiles in
  microseconds (`t_min`, `t_max`, `t_typical`, p50/p90/p99 columns
  depending on version). Report p50 and p99, not just the mean —
  tail latency is what collectives feel.
- Any run where the client and server disagree on size, count, or
  GID index is invalid. Discard it, fix the mismatch, re-run both
  sides. Never average a mismatched pair into a result.

Record template (one row per run, saved to `results.md` when real):

| Field | Value |
|---|---|
| Date / hosts / kernel | |
| Device / netdev / MTU / GID index | |
| Tool + full command line (both sides) | |
| Message size / QP count / iterations | |
| BW average, MsgRate, latency p50 / p99 (verbatim units) | |
| Host CPU during run, anything else running | |
| Verdict: pass / anomaly + one-line explanation | |

No `results.md` exists yet in this folder on purpose: it is only
created from a real run, with the tool's raw output pasted in.

## 6. Troubleshooting checklist (in the order to check)

1. **No device at all** — `ibv_devices` empty, `/sys/class/infiniband`
   missing: kernel stack not loaded or not available on this host.
   `modprobe rdma_rxe` output decides which. (2026-10-22 case: this
   step — the VM has no module tree at all.)
2. **Device exists, port not ACTIVE** — netdev down, wrong netdev in
   `rdma link add`, or link issue. Fix at `ip link` layer first.
3. **Connection hangs / times out** — IP reachability, firewall on
   the RDMA-CM / perftest TCP control port (18515 by default for
   perftest), mismatched GID index / RoCE version.
4. **QP errors, completion errors** — mismatched MTU, mismatched
   message parameters between client and server, memory registration
   limits (`ulimit -l`; perftest needs pinnable memory).
5. **Numbers absurdly low** — check negotiated link speed
   (`ethtool`), CPU saturation (Soft-RoCE is CPU-bound by design),
   and whether both ends really used the rxe device (`-d` flag).
6. **Numbers absurdly high on one host** — you measured loopback.
   Label it as a stack smoke test, not a link measurement.

## 7. Honest gap: Soft-RoCE lab vs a production IB / RoCE cluster

| Dimension | This lab (Soft-RoCE) | Production HPC / AI cluster |
|---|---|---|
| Transport device | Software rxe in the kernel, CPU does packet work | HCA / RNIC (e.g. ConnectX-class) with full offload, or a native IB HCA |
| Link | 1–25 GbE, possibly shared, lossy-tolerant setup | 100–400 Gb/s per port, engineered lossless (PFC/ECN for RoCE) or native IB credits |
| Fabric services | None — point to point, RDMA-CM only | Subnet manager / fabric manager, routing, partitioning, QoS / SL-VL mapping |
| Loss / congestion | TCP-like tolerance is not assumed, but no PFC tuning is exercised | PFC pause storms, ECN tuning, congestion control are daily operational risks |
| Scale | 2 endpoints, 1–4 QPs | Hundreds–thousands of endpoints, QP scaling, rendezvous / collective patterns |
| GPUs / jobs | None | GPUDirect RDMA, NCCL / MPI collectives, scheduler integration (e.g. Slurm) |
| Observability | perftest + `ibv_devinfo` only | Port counters, fabric diagnostics, telemetry into Prometheus/Grafana (the Module A skill) |
| What transfers | Verbs model (QP, CQ, MR, WR), RC/UD choice, GID/RoCEv2, MTU discipline, methodical bring-up | Everything in the left column still has to be re-earned at scale, on hardware |

The transferable part is the mental model and the bring-up
discipline: register memory, create QP/CQ, drive the QP through
INIT → RTR → RTS, post work requests, poll completions — and debug
by layer (kernel device → port state → CM → QP state → counters)
instead of restarting things at random. The non-transferable part —
fabric operations at scale — is stated plainly in interviews; see
[`talk-track.md`](talk-track.md).

## 8. Files in this module

```
README.md       this file — design, procedure, reading guide, gap table
attempt-log.md  verbatim 2026-10-22 attempt on the build VM: every
                command, raw output, exit code, and the failure chain
talk-track.md   3-minute interview talk track, with honest positioning
results.md      NOT PRESENT — created only from a real measured run
```

## 9. How to finish this to measured status

On any host where `modprobe rdma_rxe` succeeds (a laptop, a home-lab
box, or a cloud VM with nested/module access): run sections 3–5,
paste raw perftest output into a new `results.md` using the template
in section 5, update the status banner at the top of this file to
name the host, kernel, and date of the measured run, and keep the
original `attempt-log.md` — the failed VM attempt is part of the
evidence chain, not something to delete once a run succeeds.
