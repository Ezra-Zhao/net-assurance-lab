# Talk Track — Module B: RDMA Concept Lab (3 minutes)

Purpose: explain this proof artifact in an interview for the Atoms —
Staff HPC Network Engineer role, in about 3 minutes, without claiming
experience I do not have. Timings are guides, not a script to recite.

---

## 0:00–0:40 — Why I built it

"I know where my gap is for this role. My networking background is
data-centre build and operations — physical layer, structured cabling,
switching, and monitoring; Module A of this same repo is a Prometheus
and Grafana lab I built and actually ran. What I had never touched is
the HPC fabric side: InfiniBand, RDMA, RoCE. So instead of just
reading about it, I set up the smallest real experiment: Soft-RoCE —
the kernel's software RoCE device, rxe — with perftest, to run actual
RDMA SEND and WRITE between two endpoints and learn to read bandwidth
and latency properly."

## 0:40–1:40 — What I did, including what failed

"I want to be straight about the status: on the VM I had, the
experiment stopped at the design and attempt stage, and I documented
it that way. The VM has no kernel module tree at all — no
`/lib/modules`, no `/proc/modules`, no `/sys/class/infiniband` —
`modprobe rdma_rxe` answers 'Module rdma_rxe not found' and
`rdma link` answers 'Failed to open NETLINK_RDMA socket'. Every
command and its raw output is in `attempt-log.md`. I did not dress
the design up as a measurement.

What is complete is the procedure: load `ib_core`, `ib_uverbs`,
`rdma_rxe`; create `rxe0` on a netdev with `rdma link add`; verify
with `rdma link show`, `ibv_devices`, and `ibv_devinfo` that the port
is ACTIVE and the link layer is Ethernet; then server/client
`ib_send_bw`, `ib_write_bw`, and `ib_send_lat` with an explicit GID
index and message-size sweep, recording p50 and p99 latency, not just
average bandwidth. On any host that can load the module, that runs
as written, and the README says exactly how it graduates to a
measured result."

## 1:40–2:30 — Soft-RoCE vs production InfiniBand / RoCE

"Soft-RoCE teaches the verbs model — queue pairs, completion queues,
memory registration, the INIT to RTR to RTS state machine, RoCEv2
GIDs, MTU discipline. That model is the same on real hardware.

What it does not teach, and I won't pretend otherwise: there is no
HCA offload — the CPU does all the packet work, so the numbers cap
out far below wire rate and mostly measure the host. There is no
fabric: no subnet manager, no lossless configuration, no PFC or ECN
tuning, no congestion behaviour, no QP scaling across hundreds of
nodes, no GPUDirect or NCCL collectives. A production NDR fabric is
a different operational discipline. My lab is the on-ramp to that
vocabulary, not a substitute for having run that fabric."

## 2:30–3:00 — Honest positioning and what I bring instead

"So my positioning is: this is a document-level proof — it shows I
can scope an unfamiliar stack, attempt it for real, diagnose exactly
which layer blocked me, and write a reproducible procedure with
honest pass criteria. It is not HPC fabric experience, and if you
need someone who has operated a large IB fabric on day one, that is
not me yet.

What I do bring on day one is the surrounding discipline this role
also needs: data-centre physical-layer work, methodical fault
isolation — Module A localises loss versus delay versus flap from
packet-level evidence instead of guessing — and production-style
observability with Prometheus and Grafana. The RDMA mental model is
now in place; the fastest way for me to close the rest is on real
hardware, in a real fabric, with exactly this bring-up checklist in
hand."

---

## Likely follow-ups — short honest answers

- **"RC vs UD?"** — Reliable Connection: per-peer QP, reliable,
  supports RDMA READ/WRITE, the default for perftest and most HPC
  point-to-point traffic. Unreliable Datagram: connectionless,
  SEND-only, scales to many peers, no hardware reliability. Start
  with RC; reach for UD/UC only with a scaling reason.
- **"RoCEv1 vs RoCEv2?"** — v1 is Ethernet-layer (L2 only, one
  broadcast domain, Ethertype-based). v2 wraps the payload in
  UDP/IP, so it routes at L3 — that is why the GID index and the
  UDP source-port / ECN behaviour matter in production RoCE.
- **"Why does lossless matter for RoCE and not for iWARP?"** —
  Classic RoCE assumes a lossless Ethernet fabric (PFC) because the
  base protocol has limited retransmission behaviour; iWARP runs
  over TCP and inherits its reliability, at different offload and
  latency trade-offs.
- **"First thing you check when a link won't come up?"** — Layer by
  layer, in order: kernel device present, port state ACTIVE, IP
  reachability, GID/RoCE version match, MTU match, then QP state.
  The attempt log is that order, applied to a host that failed at
  layer one.
- **"Your p99 is terrible but average bandwidth looks fine — why?"**
  — Averages hide tail behaviour: CPU saturation on a software
  device, congestion / pause, or a mismatched MTU forcing retries
  all hit the tail first. That is why the lab records p50/p99, and
  why Module A reports RTT percentiles the same way.
