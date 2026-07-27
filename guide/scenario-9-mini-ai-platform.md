# Scenario 9 — The Mini AI Platform: Kueue, Batch Jobs & LLM Serving

- **Goal** — Build a working AI platform in miniature: team quotas and job queueing with Kueue, gang-style batch “training” jobs competing for capacity, a real LLM served from the cluster on CPU — and the honest hybrid that puts your 40-core GPU to work.
- **Time** — ~2–3 hours (model pulls included)
- **Concepts** — Job queueing (Kueue) · batch Jobs · LLM serving · efficiency metrics
- **Requires** — Docker VM ≥ 12 CPU / 48 GB. The 3-node `practice` cluster works; give it more per-node memory if rebuilding: `--memory=8192`.

## Act 1 — Install Kueue and model two teams

```bash
$ VERSION=$(curl -s https://api.github.com/repos/kubernetes-sigs/kueue/releases/latest | grep tag_name | cut -d'"' -f4)
$ kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/$VERSION/manifests.yaml
$ kubectl get pods -n kueue-system
kueue-controller-manager-7d9c8b6f54-x2kqm   1/1     Running   0          60s

# kueue-setup.yaml — one flavor, two team queues sharing 8 CPUs of "cluster" capacity:
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata: {name: default-flavor}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata: {name: team-research}
spec:
  namespaceSelector: {}
  resourceGroups:
  - coveredResources: [cpu, memory]
    flavors:
    - name: default-flavor
      resources:
      - {name: cpu, nominalQuota: 6}      # research gets 6 CPUs…
      - {name: memory, nominalQuota: 12Gi}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata: {name: team-app}
spec:
  namespaceSelector: {}
  resourceGroups:
  - coveredResources: [cpu, memory]
    flavors:
    - name: default-flavor
      resources:
      - {name: cpu, nominalQuota: 2}      # …app team gets 2
      - {name: memory, nominalQuota: 4Gi}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata: {name: research-queue, namespace: ai-lab}
spec: {clusterQueue: team-research}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata: {name: app-queue, namespace: ai-lab}
spec: {clusterQueue: team-app}
```

```bash
$ kubectl create namespace ai-lab && kubectl apply -f kueue-setup.yaml
$ kubectl config set-context --current --namespace=ai-lab
```

## Act 2 — Queueing in action: more jobs than cluster

```yaml
# train-job.yaml — a fake "training run": 2 parallel workers × 3 CPUs of matrix math.
# The kueue label is how a Job joins a queue (labels doing the heavy lifting, again):
apiVersion: batch/v1
kind: Job
metadata:
  generateName: train-
  labels: {kueue.x-k8s.io/queue-name: research-queue}
spec:
  parallelism: 2
  completions: 2
  suspend: true                     # Kueue admits (unsuspends) it when quota allows
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: trainer
        image: python:3.12-slim
        command: [sh, -c]
        args:
        - |
          pip install --quiet numpy && python - <<'PY'
          import numpy as np, time
          t0 = time.time(); steps = 0
          while time.time() - t0 < 180:                    # 3 minutes of "training"
              a = np.random.rand(1200,1200) @ np.random.rand(1200,1200)
              steps += 1
          print(f"training complete: {steps} steps")
          PY
        resources:
          requests: {cpu: "3", memory: 1Gi}
          limits:   {cpu: "3", memory: 2Gi}
```

```bash
# Submit THREE runs = 3 × (2 pods × 3 CPU) = 18 CPUs of demand into a 6-CPU quota:
$ kubectl create -f train-job.yaml && kubectl create -f train-job.yaml && kubectl create -f train-job.yaml
$ kubectl get workloads
NAME                       QUEUE            RESERVED IN     ADMITTED   AGE
job-train-8kzq2-7f4d2      research-queue   team-research   True       30s
job-train-p71xd-9c8b1      research-queue                   False      25s
job-train-ww4mn-2e6a5      research-queue                   False      20s
# ONE run admitted (6/6 CPUs used); two WAIT IN QUEUE — not Pending-forever pods,
# but suspended Jobs. As each run finishes, Kueue admits the next. Watch the handoff:
$ kubectl get workloads -w
# This is the whole argument for job queueing in one screen: quota + queueing beats
# scheduler-deadlock. Submit a job to app-queue and see it run IMMEDIATELY —
# separate team, separate quota, no queue-jumping between teams.
```

## Act 3 — Serve a real LLM from the cluster (CPU)

```yaml
# model-cache-pvc.yaml — the weights cache that outlives every pod:
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: model-cache}
spec:
  storageClassName: csi-hostpath-sc
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 10Gi}}
```

```yaml
# llm.yaml — Ollama + a 1B-parameter model, entirely inside the cluster:
apiVersion: apps/v1
kind: Deployment
metadata: {name: llm}
spec:
  replicas: 1
  selector: {matchLabels: {app: llm}}
  template:
    metadata: {labels: {app: llm}}
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest       # multi-arch: runs arm64-native
        ports: [{containerPort: 11434}]
        resources:
          requests: {cpu: "2", memory: 4Gi}
          limits:   {cpu: "4", memory: 8Gi}
        volumeMounts: [{name: models, mountPath: /root/.ollama}]
        readinessProbe:
          httpGet: {path: /, port: 11434}
          initialDelaySeconds: 10
      volumes:
      - name: models
        persistentVolumeClaim: {claimName: model-cache}   # shared model-cache pattern:
                                                             # weights survive pod restarts
```

```bash
$ kubectl apply -f model-cache-pvc.yaml -f llm.yaml
$ kubectl expose deployment llm --port=11434
$ kubectl exec -it deploy/llm -- ollama pull llama3.2:1b  # ~1.3GB, one-time (cached in the PVC)

$ kubectl run prompt --image=curlimages/curl --restart=Never --rm -it -- \
    curl -s http://llm:11434/api/generate -d '{
      "model":"llama3.2:1b",
      "prompt":"Explain a Kubernetes pod in one sentence.",
      "stream":false}'
{"model":"llama3.2:1b","response":"A Kubernetes pod is the smallest deployable unit
that wraps one or more containers sharing network and storage...","done":true,
"eval_count":31,"eval_duration":2412000000,...}
# Real tokens from a real model, served by YOUR cluster. eval_duration ≈ 2.4s
# for ~31 tokens on CPU — remember that number for Act 4.
```

## Act 4 — The honest hybrid: put the 40-core GPU in the loop

Containers can't see Apple's GPU ([setup §5](00-setup-and-operations.md#5-scaling-up-the-lab-on-an-m5-max-128-gb)) — but real platforms constantly front models they don't host. So run Ollama *natively on macOS* (Metal-accelerated) and let the cluster treat it as an external backend — the same shape real platforms use: an inference gateway in the cluster, a GPU pool behind it:

```bash
# On the Mac (Terminal, not the cluster):
$ brew install ollama
$ OLLAMA_HOST=0.0.0.0 ollama serve &
$ ollama pull llama3.2:3b                  # bigger model — your GPU can afford it

# In the cluster: a selector-less Service backed by a MANUAL EndpointSlice
# pointing at your Mac. (Why not ExternalName → host.minikube.internal? That name
# lives only in the NODES' /etc/hosts — CoreDNS can't resolve it for pods. So we
# grab the host's IP from a node and wire it in explicitly — which is also exactly
# how you'd front any external backend in production.)
$ HOSTIP=$(minikube ssh -p practice "grep host.minikube.internal /etc/hosts | cut -f1" | tr -d '\r')
$ echo $HOSTIP
192.168.65.254                             # typical on Docker Desktop; yours may differ
$ kubectl apply -f - <<EOF
apiVersion: v1
kind: Service
metadata: {name: gpu-llm}
spec:
  ports: [{port: 11434, targetPort: 11434}]
---
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: gpu-llm-1
  labels: {kubernetes.io/service-name: gpu-llm}
addressType: IPv4
ports: [{port: 11434, protocol: TCP}]
endpoints:
- addresses: ["$HOSTIP"]
EOF
$ kubectl run prompt --image=curlimages/curl --restart=Never --rm -it -- \
    curl -s http://gpu-llm:11434/api/generate -d '{
      "model":"llama3.2:3b","prompt":"Explain a Kubernetes pod in one sentence.","stream":false}'
{"model":"llama3.2:3b","response":"...","done":true,
"eval_count":34,"eval_duration":510000000,...}
# ~0.5s on the Metal-accelerated 3B vs ~2.4s on the CPU-bound 1B: the GPU is now
# in your serving path, brokered through a cluster Service. Compare architectures:
# in-cluster CPU model = self-hosted inference; Service + manual EndpointSlice to
# the host = external GPU pool. Both halves of a real inference platform, on one laptop. (Bonus:
# you just hand-authored an EndpointSlice — the object services normally manage
# for you, and the first thing to inspect in Drill 4-style "nothing answers" bugs.)
```

> **STRETCH GOALS** — ① Autoscale the CPU LLM: HPA on the llm deployment, load it with parallel prompts, watch replicas grow — then hit the wall: the model-cache PVC is ReadWriteOnce on a node-local CSI driver, so replicas landing on *other* nodes stick in ContainerCreating. Diagnose it, then pin replicas to one node (nodeSelector) or give each its own cache. That wall is precisely why real platforms use RWX model caches (the industry's shared-model-cache pattern). ② Add a NetworkPolicy so only pods labeled `role=prompt-gw` may reach the llm service (Scenario 5 skills). ③ Put the whole ai-lab namespace under an Argo CD Application (Scenario 8) and manage your AI platform from git.

## Cleanup

```bash
$ kubectl delete namespace ai-lab
$ kubectl delete clusterqueue team-research team-app && kubectl delete resourceflavor default-flavor
$ pkill ollama                             # stop the native server on the Mac
$ kubectl config set-context --current --namespace=default
```

---

> **WAIT — DID WE SAY "NO GPU IN THE CLUSTER"?** — Yes… and no. Everything above is true *for the docker driver*, and the hybrid you just built remains the right architecture on it. But if you're willing to abandon the easy docker path for one special-purpose cluster, there is now a stack that puts your Apple GPU *inside pods* — a different minikube driver, a device plugin, and Vulkan doing the translation. It has real trade-offs, which is exactly why it earns its own scenario rather than a footnote: **[Scenario 10 — The GPU, Unlocked](scenario-10-gpu-unlocked.md)**.
