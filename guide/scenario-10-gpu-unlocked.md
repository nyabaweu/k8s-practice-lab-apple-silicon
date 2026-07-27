# Scenario 10 — The GPU, Unlocked: krunkit, Device Plugins & Vulkan Inference

*Added after initial release — Scenarios 1–9 are unchanged and remain fully valid.*

Scenario 9 ended with an honest limitation: on the docker driver, the Apple GPU is invisible to pods — full stop, still true. So did we oversell the limitation? **Yes and no.** The GPU is unreachable *from Docker Desktop's VM*, and that driver remains this lab's daily recommendation for good reasons (multi-node, dead-simple, battle-tested SME2 masking). But minikube's newer **krunkit** driver (shipped in v1.37, Sept 2025, with an [official upstream tutorial](https://minikube.sigs.k8s.io/docs/tutorials/ai-playground/)) takes a different road: it virtualizes the GPU into the VM, a device plugin advertises it to Kubernetes, and pods run *GPU-accelerated inference*. The price of admission: a separate single-node cluster, a Vulkan translation layer instead of native Metal, and a few more moving parts. This scenario builds that world alongside your existing one — nothing from Scenarios 1–9 changes.

- **Goal** — Stand up a GPU-enabled krunkit cluster, teach Kubernetes to schedule the Apple GPU via a device plugin, serve a real model on it, and hit the sharing limits on purpose.
- **Time** — ~90 minutes (model download included)
- **Concepts** — VM drivers & virtio-gpu · device plugins & extended resources · Vulkan/Venus inference · scheduling against device counts
- **Requires** — Apple Silicon · macOS 14+ (macOS 26 Tahoe is smoothest: no sudo for networking) · minikube ≥ 1.38.1 · ~14 GB free RAM while running

## First, the honest physics (read before typing)

- **This is not true GPU passthrough** — Apple GPUs can't be handed to a VM (no IOMMU for that). Instead: the pod's app speaks **Vulkan** → Mesa's *Venus* driver forwards it over **virtio-gpu** → the host translates via **MoltenVK** → **Metal** → your GPU cores. API virtualization, four hops, genuinely GPU-fast.
- **Expect ~50–80% of native Metal** throughput, and several-times-faster-than-CPU (community benchmarks: a 7B model at ~36 tok/s in-VM vs ~71 native on an M2 Max; Red Hat measured 75–80% of native on 1B–13B models). Never expect "native speed" — that claim belongs to a separate experimental path (API remoting) not used here.
- **M4/M5-safe, independently:** libkrun (under krunkit) has masked the SME CPU features since v1.19.0 (June 2025) — this stack avoids the SIGILL saga by its own route. The two engines in this lab are *both* safe; they just unlock different superpowers.
- **Single-node** is the only documented topology, and GPU access via the device plugin is *cooperative sharing* — no isolation between pods (the exact problem datacenter GPUs solve with hardware MIG partitioning; here you get the honor system).

## Act 1 — Install the GPU stack and start the cluster

```bash
# krunkit (the VM engine) — note: the Homebrew tap moved to the libkrun org;
# older guides say "slp/krunkit" — same software, new home:
$ brew tap libkrun/krun && brew install krunkit
$ krunkit --version
krunkit 1.0.x                              # need ≥ 1.0.0

# vmnet-helper (networking — krunkit has no built-in NAT; this bridges it,
# and on macOS 26 it runs with NO sudo at all):
$ curl -fsSL https://github.com/minikube-machine/vmnet-helper/releases/latest/download/install.sh | bash

# A model to serve — must be GGUF format. ~1.2 GB, one-time download:
$ mkdir -p ~/models && cd ~/models
$ curl -LO https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q8_0.gguf

# The GPU cluster — a SEPARATE profile; your practice/fleet clusters are untouched.
# --memory is on you: model + KV cache must fit the VM (the tutorial omits this; don't):
$ minikube start --profile=gpu --driver=krunkit --memory=12288 --cpus=6 \
    --mount-string ~/models:/mnt/models
😄  [gpu] minikube v1.38.x on Darwin 26.5.1 (arm64)
✨  Using the krunkit driver based on user configuration
🔥  Creating krunkit VM (CPUs=6, Memory=12288MB) ...
🏄  Done! kubectl is now configured to use "gpu" cluster

# The moment of truth — does the VM see a GPU device?
$ minikube ssh -p gpu -- ls -la /dev/dri
crw-rw---- 1 root video 226,   0 Jul 16 14:02 card0
crw-rw---- 1 root render 226, 128 Jul 16 14:02 renderD128   # renderD128 = your Apple GPU,
                                                             # wearing a Linux DRM costume
```

## Act 2 — Teach Kubernetes the GPU exists (the device plugin)

A raw `/dev/dri` node means nothing to the scheduler. Enter the device-plugin pattern — the same mechanism NVIDIA's GPU Operator uses in datacenters, in miniature. The `generic-device-plugin` DaemonSet advertises the device as an *extended resource* pods can request (manifest: [`manifests/scenario-10/gpu-device-plugin.yaml`](../manifests/scenario-10/gpu-device-plugin.yaml)):

```bash
$ kubectl apply -f gpu-device-plugin.yaml
$ kubectl describe node gpu | grep -A4 Allocatable:
Allocatable:
  cpu:                6
  devic.es/dri:       4          # there it is — the Apple GPU as a schedulable K8s
                                 # resource. (devic.es is the plugin's real domain name,
                                 # not a typo.) Compare: nvidia.com/gpu in the datacenter.
```

The `count: 4` in the plugin config means up to 4 pods may share `/dev/dri` — sharing, NOT isolation.

## Act 3 — Serve a model ON the GPU

The deployment ([`manifests/scenario-10/llm-gpu.yaml`](../manifests/scenario-10/llm-gpu.yaml)) runs `llama-server` from the ramalama image (which ships llama.cpp's Vulkan backend plus the Mesa/Venus userspace this VM needs), with `-ngl 999` (all layers to GPU) and the key line:

```yaml
        resources:
          limits:
            devic.es/dri: 1              # the whole point of Act 2
            memory: 4Gi
```

```bash
$ kubectl apply -f llm-gpu.yaml && kubectl expose deployment llm-gpu --port=8080
$ kubectl logs deploy/llm-gpu | grep -i vulkan
ggml_vulkan: Found 1 Vulkan devices:
ggml_vulkan: 0 = Virtio-GPU Venus (Apple M5 Max) ...   # Vulkan sees your GPU through the VM

$ kubectl run prompt --image=curlimages/curl --restart=Never --rm -it -- \
    curl -s http://llm-gpu:8080/completion -d '{
      "prompt":"Explain a Kubernetes pod in one sentence.","n_predict":48}'
{"content":" A pod is the smallest deployable unit in Kubernetes, wrapping one or
more containers that share networking and storage...",
 "timings":{"predicted_per_second":57.8,...}}
# ~58 tok/s from a pod. Scenario 9's in-cluster CPU pod managed ~13 tok/s on a
# similar-size model; native Metal would do roughly 75-100+. That's the deal in one
# line: several-times faster than CPU, ~50-80% of native — paid for with one extra
# driver and a Vulkan translation layer.
```

## Act 4 — Hit the sharing wall on purpose

```bash
# Act 2's device plugin advertised count: 4. Let's spend it all:
$ kubectl scale deployment llm-gpu --replicas=5
$ kubectl get pods
NAME                       READY   STATUS    RESTARTS   AGE
llm-gpu-6f9c8d7b54-2kq8x   1/1     Running   0          8m
llm-gpu-6f9c8d7b54-9mzw4   1/1     Running   0          50s
llm-gpu-6f9c8d7b54-kk3fd   1/1     Running   0          50s
llm-gpu-6f9c8d7b54-tt7lg   1/1     Running   0          50s
llm-gpu-6f9c8d7b54-vv9qk   0/1     Pending   0          50s   # 4 Running, 1 Pending

$ kubectl describe pod llm-gpu-6f9c8d7b54-vv9qk | grep -A2 Events:
Events:
  Warning  FailedScheduling  ...  0/1 nodes are available: 1 Insufficient devic.es/dri.
# The same "Insufficient" grammar as Drill 1 — but now the scarce resource is a GPU.
# And note what count:4 really bought you: FOUR pods time-sharing ONE GPU with no
# isolation — one greedy pod can starve the others. Datacenter GPUs solve this with
# hardware partitioning (MIG); your laptop just taught you why that exists.
$ kubectl scale deployment llm-gpu --replicas=1
```

## What can bite you (field notes)

| Symptom | Cause & fix |
|---|---|
| `driver 'krunkit' is not supported` | minikube older than v1.37 — `brew upgrade minikube` (this lab pins ≥1.38.1). |
| Cluster start hangs on networking | vmnet-helper missing or unauthorized. macOS ≤15 needs its sudoers file (see its install docs); macOS 26+ needs nothing. Logs: `~/.minikube/machines/gpu/vmnet-helper.log`. |
| `brew tap slp/krunkit` fails | The tap moved to `libkrun/krun` (older tutorials have the stale name). |
| llama-server CrashLoopBackOff | Usually the model path — did you pass `--mount-string` at `minikube start`? It cannot be added to a running VM. Or the model isn't GGUF. |
| OOM / VM freeze under load | Model + context must fit the VM's memory. Size `--memory` generously (12 GB here); bigger models (7B Q4 ≈ 4.2 GB file) need more. |
| Slow despite GPU | Check the Vulkan line in logs (Act 3). Avoid flash-attention flags on Vulkan; stick to Q4/Q8 quantizations. |

> **WHAT THIS SCENARIO PROVED** — The docker-driver limitation was real — and so is the door around it. More importantly, you just ran the *datacenter GPU pattern end to end in miniature*: a device exposed to a VM, a device plugin advertising it as a schedulable resource, workloads requesting it by name, and the scheduler enforcing scarcity. Swap `devic.es/dri` for `nvidia.com/gpu`, the DaemonSet for the NVIDIA GPU Operator, and count-sharing for MIG partitions — same architecture, three more zeros on the price tag.

## Cleanup

```bash
$ minikube delete --profile=gpu            # the GPU world vanishes entirely
$ minikube start --profile=practice        # daily lab, exactly as you left it
# ~/models is on your Mac — keep it; downloads are the slow part.
```

*Credit: cluster recipe based on the official [minikube AI Playground tutorial](https://minikube.sigs.k8s.io/docs/tutorials/ai-playground/); GPU virtualization stack by the [libkrun](https://github.com/libkrun/libkrun) project.*
