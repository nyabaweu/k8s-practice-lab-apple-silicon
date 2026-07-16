# Scenario 7 — The Nine-Node Fleet: HA, Placement & Chaos

- **Goal** — Operate a 9-node, 3-control-plane cluster: steer pods with taints/affinity/spread, protect them with PodDisruptionBudgets, then run a chaos gauntlet — including killing a control-plane node — and watch the cluster shrug.
- **Time** — ~2 hours
- **Concepts** — Control plane & etcd quorum · taints · topology spread · PDBs · failure playbook
- **Requires** — Docker VM at 12 CPU / 48 GB ([setup §5](00-setup-and-operations.md#5-scaling-up-the-lab-on-an-m5-max-128-gb)). Stop the `practice` profile first.

## Act 1 — Build the fleet

```bash
$ minikube stop --profile=practice
$ minikube start --profile=fleet --driver=docker --ha --nodes=9 \
    --cni=calico --cpus=2 --memory=4096 --kubernetes-version=v1.34.1
$ kubectl get nodes
NAME        STATUS   ROLES           AGE   VERSION
fleet       Ready    control-plane   9m    v1.34.1
fleet-m02   Ready    control-plane   8m    v1.34.1
fleet-m03   Ready    control-plane   7m    v1.34.1
fleet-m04   Ready    <none>          6m    v1.34.1
fleet-m05   Ready    <none>          5m    v1.34.1
fleet-m06   Ready    <none>          5m    v1.34.1
fleet-m07   Ready    <none>          4m    v1.34.1
fleet-m08   Ready    <none>          3m    v1.34.1
fleet-m09   Ready    <none>          3m    v1.34.1   # three control planes — real HA topology
```

## Act 2 — Carve the fleet into zones (labels + taints)

```bash
# Pretend m04–m06 are rack A, m07–m09 are rack B; m09 is "special hardware":
$ kubectl label node fleet-m04 fleet-m05 fleet-m06 topology.kubernetes.io/zone=rack-a
$ kubectl label node fleet-m07 fleet-m08 fleet-m09 topology.kubernetes.io/zone=rack-b
$ kubectl taint node fleet-m09 hardware=special:NoSchedule   # the classic "GPU-node" taint pattern

$ kubectl create namespace fleet-lab && kubectl config set-context --current --namespace=fleet-lab

# spread.yaml — 12 replicas that MUST spread evenly across zones:
apiVersion: apps/v1
kind: Deployment
metadata: {name: spread-app}
spec:
  replicas: 12
  selector: {matchLabels: {app: spread-app}}
  template:
    metadata: {labels: {app: spread-app}}
    spec:
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: topology.kubernetes.io/zone
        whenUnsatisfiable: DoNotSchedule
        labelSelector: {matchLabels: {app: spread-app}}
      containers:
      - name: app
        image: nginx:1.27
        resources: {requests: {cpu: 100m, memory: 64Mi}}
```

```bash
$ kubectl apply -f spread.yaml
$ kubectl get pods -o wide --no-headers | awk '{print $7}' | sort | uniq -c
   2 fleet-m04
   2 fleet-m05
   2 fleet-m06
   3 fleet-m07
   3 fleet-m08          # 6 in rack-a, 6 in rack-b (skew ≤1), and NOTHING on m09 —
                          # the taint repels pods that don't tolerate it. Verify the zone
                          # math; note m09 idle exactly as designed.
```

## Act 3 — Claim the special node, protect the app

```bash
# A workload that TOLERATES the taint and INSISTS on rack-b + the special node:
$ kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: special-app}
spec:
  replicas: 2
  selector: {matchLabels: {app: special-app}}
  template:
    metadata: {labels: {app: special-app}}
    spec:
      tolerations:
      - {key: hardware, operator: Equal, value: special, effect: NoSchedule}
      nodeSelector: {kubernetes.io/hostname: fleet-m09}
      containers:
      - name: app
        image: nginx:1.27
EOF
$ kubectl get pods -l app=special-app -o wide
special-app-...-2kq8x   1/1   Running   0   15s   10.244.201.7   fleet-m09
special-app-...-9mzw4   1/1   Running   0   15s   10.244.201.8   fleet-m09

# PodDisruptionBudget — the seatbelt for maintenance:
$ kubectl create poddisruptionbudget spread-pdb --selector=app=spread-app --min-available=9
```

## Act 4 — Maintenance day (voluntary disruption)

```bash
$ kubectl drain fleet-m05 --ignore-daemonsets --delete-emptydir-data
node/fleet-m05 cordoned
evicting pod fleet-lab/spread-app-7f6d8c9b54-4kzmq
evicting pod fleet-lab/spread-app-7f6d8c9b54-8xw2l
pod/spread-app-7f6d8c9b54-4kzmq evicted
pod/spread-app-7f6d8c9b54-8xw2l evicted
node/fleet-m05 drained
# The PDB paced the evictions so ≥9 stayed available; the spread constraint
# re-placed the evicted pods within rack-a (m04/m06). Check both claims:
$ kubectl get pods -o wide --no-headers | awk '{print $7}' | sort | uniq -c
# "Patch" the node and return it to service:
$ kubectl uncordon fleet-m05
```

## Act 5 — Chaos gauntlet (involuntary disruption)

```bash
# ① Kill a worker cold (no drain, no warning):
$ docker kill fleet-m07
$ kubectl get nodes -w
fleet-m07   NotReady   <none>   40m   v1.34.1       # ~40s later
# ~5 min later: its pods are evicted and rebuilt on m04–m08, spread constraints
# still honored. Bring it back: docker start fleet-m07 → Ready again.

# ② The big one — kill a CONTROL-PLANE node:
$ docker kill fleet-m02
$ kubectl get nodes                                  # still answers! HA means the API
                                                       # survives a control-plane death
NAME        STATUS     ROLES           AGE   VERSION
fleet       Ready      control-plane   55m   v1.34.1
fleet-m02   NotReady   control-plane   54m   v1.34.1
fleet-m03   Ready      control-plane   53m   v1.34.1
...
$ kubectl create deployment prove-it --image=nginx:1.27   # scheduling still works too
deployment.apps/prove-it created
$ docker start fleet-m02                             # heal; watch etcd re-sync it in

# ③ Watch etcd quorum in action (the "why 3 control planes" lesson):
#    with m02 down you had 2/3 etcd members = quorum held. Kill TWO control
#    planes and the API server stops answering — try it, feel the fear, restart them.
```

> **WHAT THIS SCENARIO PROVED** — The classic failure playbook — detect, cordon/drain, diagnose, return — plus the etcd-quorum reality: losing etcd quorum means losing the cluster's brain. You have now personally survived a control-plane failure. Most engineers never get to practice that safely.

## Cleanup

```bash
$ minikube delete --profile=fleet
$ minikube start --profile=practice       # back to the daily lab
```
