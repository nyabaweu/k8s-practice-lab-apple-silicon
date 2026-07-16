# Kubernetes Practice Lab on the MacBook Pro (Apple Silicon M5)

A complete, hands-on Kubernetes learning lab for Apple Silicon Macs — install and operate a real multi-node cluster on your laptop, then master it through **nine end-to-end scenarios** that go from your first deployment to a nine-node chaos fleet, GitOps, and a miniature AI platform.

Every scenario shows the **exact output you should expect** at each step, stages a deliberate failure or surprise to investigate, and ends with a clean teardown. Everything is disposable by design — break things fearlessly.

> **Why this exists:** running Kubernetes on M4/M5-generation Apple Silicon has real pitfalls (SME2 CPU-feature crashes in most VM stacks, no GPU passthrough, docker-driver capacity quirks). This lab documents a stack verified to work — **Docker Desktop + minikube + Calico** — and turns the platform's limits into lessons instead of surprises.

## ⚠️ System requirements — read this first

| Requirement | Minimum (Scenarios 1–6) | Recommended (Scenarios 7–9) |
|---|---|---|
| **Mac** | Apple Silicon MacBook Pro/Air (M1–M5) — written for and tested on the M5 generation | M-series **Pro/Max** with **48 GB+ unified memory** (developed on an M5 Max, 128 GB) |
| **macOS** | **26 “Tahoe”, version 26.5.1 or later** — 26.5.1 contains an M5-specific stability fix; older Tahoe builds can shut down unexpectedly under container load | same |
| **Docker Desktop** | **≥ 4.80**, Apple Silicon build, VM sized 6 CPU / **8 GB** / 60 GB | VM sized 12 CPU / **48 GB** / 120 GB |
| **Free disk** | ~80 GB | ~150 GB |
| **Tooling** | minikube v1.38+ · kubectl · helm · k9s (all via Homebrew) | same |
| **Kubernetes** | v1.34.x (pinned in every `minikube start` in this guide) | same |
| **Network** | Internet for image pulls (several GB on first run) | same |

> **Intel Macs are not supported** by this guide (different virtualization stack, different pitfalls). On **M4/M5 Macs specifically, do not substitute Podman machine, Colima/Lima, or QEMU-based engines** — as of mid-2026 they expose SME/SME2 CPU features to Linux guests and workloads crash with SIGILL. Docker Desktop masks these features; that's why it's the required engine here.

## Environment summary

| Component | Choice | Why |
|---|---|---|
| Engine | Docker Desktop ≥ 4.80 (free for personal use) | The one engine confirmed to mask M5 SME2 CPU features |
| Cluster | minikube v1.38 · Kubernetes v1.34 · 3 nodes (docker driver) | One command for multi-node; one-line addons |
| CNI | Calico | Real NetworkPolicy enforcement (Scenario 5 depends on it) |
| Tools | kubectl · helm · k9s | All free, Apache-2.0 |

## Start here

1. **[Part A — Setup & Operations](guide/00-setup-and-operations.md)** — full install record, daily start/stop, session wrap-up, and the big-memory scale-up.
2. Then work the scenarios in order:

| # | Scenario | Level | Time | You walk away with |
|---|---|---|---|---|
| 1 | [Hello, Cluster: Deploy, Break, Self-Heal](guide/scenario-1-hello-cluster.md) | Basic | ~30 min | Reading the self-healing loop live; node-failure recovery |
| 2 | [The Config Kitchen: ConfigMaps, Secrets & Probes](guide/scenario-2-config-kitchen.md) | Basic | ~45 min | Config-vs-restart semantics; probes that auto-heal deadlocks |
| 3 | [Storage That Survives: PVCs, a Database & Snapshots](guide/scenario-3-storage-that-survives.md) | Basic | ~45 min | Dynamic provisioning; snapshot → restore |
| 4 | [Bookshelf: Three Tiers, Ingress & Autoscaling](guide/scenario-4-bookshelf.md) | Medium | ~90 min | A real 3-tier app; HPA under load; zero-downtime rollouts |
| 5 | [Lock It Down: NetworkPolicies & RBAC](guide/scenario-5-lock-it-down.md) | Medium | ~60 min | Default-deny networking; least-privilege RBAC with `--as` |
| 6 | [Break It On Purpose: Troubleshooting Drills](guide/scenario-6-break-it-on-purpose.md) | Medium | ~90 min | The describe → events → logs diagnostic reflex (CKA-style) |
| 7 | [The Nine-Node Fleet: HA, Placement & Chaos](guide/scenario-7-nine-node-fleet.md) | Advanced | ~2 h | Taints, spread, PDBs; surviving control-plane loss; etcd quorum |
| 8 | [GitOps & Observability: Argo CD + Prometheus/Grafana](guide/scenario-8-gitops-observability.md) | Advanced | ~2 h | Drift-correcting GitOps; the metrics → dashboards → alerts loop |
| 9 | [The Mini AI Platform: Kueue, Batch Jobs & LLM Serving](guide/scenario-9-mini-ai-platform.md) | Advanced | ~2–3 h | Team quotas & job queueing; LLM serving; a hybrid GPU architecture |

3. Keep the **[Appendix — Concept Map & Quick Reference](guide/appendix-quick-reference.md)** handy.

Ready-to-apply YAML for the bigger builds lives in [`manifests/`](manifests/), organized per scenario.

## Quickstart (if you just want the cluster)

```bash
brew install --cask docker-desktop        # then launch it; Settings → Resources: 6 CPU / 8 GB / 60 GB
brew install minikube kubectl helm k9s
minikube start --profile=practice --driver=docker --nodes=3 --cni=calico \
  --cpus=2 --memory=2200 --kubernetes-version=v1.34.1
minikube addons enable metrics-server ingress dashboard csi-hostpath-driver volumesnapshots --profile=practice
kubectl taint node practice node-role.kubernetes.io/control-plane=:NoSchedule
kubectl get nodes                          # 3 × Ready → you're in business
```

*(The addons line is shorthand — enable them one at a time if your minikube version rejects multiple names.)*

## Honest limitations

- **No GPU passthrough** — no container on macOS can see the Apple GPU. Scenario 9 shows the honest hybrid (native Metal-accelerated Ollama fronted by a cluster Service).
- **No OS-level node ops** — nodes are containers, so kubeadm upgrades and etcd-backup drills need real VMs.
- Docker-driver nodes report the whole VM's capacity; the setup guide explains the quirks this causes.

## Contributing

Corrections and new scenarios welcome — open an issue or PR. Expected outputs are representative (pod hashes, IPs and ages will differ); if a command's *shape* of output has drifted with newer versions, that's a bug worth reporting.

## License

[MIT](LICENSE) — use it, fork it, teach with it.
