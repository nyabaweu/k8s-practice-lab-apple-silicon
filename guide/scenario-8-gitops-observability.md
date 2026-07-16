# Scenario 8 — GitOps & Observability: Argo CD + Prometheus/Grafana

- **Goal** — Stop kubectl-ing changes into clusters by hand: install Argo CD, let git drive deployments (including a self-healing demo when you tamper live), and stand up the kube-prometheus-stack to watch it all on Grafana dashboards.
- **Time** — ~2 hours
- **Concepts** — Helm · operators/CRDs · GitOps · observability-before-users
- **Requires** — The 3-node `practice` cluster is fine; bump Docker VM to ≥16 GB for comfort (prometheus stack is hungry).

## Act 1 — Argo CD

```bash
$ kubectl create namespace argocd
$ kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
$ kubectl get pods -n argocd
NAME                                  READY   STATUS    RESTARTS   AGE
argocd-application-controller-0       1/1     Running   0          2m
argocd-repo-server-5f7b8c9d6-k2xwq    1/1     Running   0          2m
argocd-server-7d8c9b6f54-9mzw4       1/1     Running   0          2m
... (7 pods total)

# Log in to the UI:
$ kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo
x8Kp2mQr9vLwZn4T                          # yours will differ — this is the admin password
$ kubectl port-forward svc/argocd-server -n argocd 8443:443
# Browser → https://localhost:8443 → accept the self-signed cert → admin / <password>
```

## Act 2 — An app that git controls, not you

```yaml
# app.yaml — point Argo CD at the public example repo (guestbook):
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata: {name: guestbook, namespace: argocd}
spec:
  project: default
  source:
    repoURL: https://github.com/argoproj/argocd-example-apps
    targetRevision: HEAD
    path: guestbook
  destination:
    server: https://kubernetes.default.svc
    namespace: guestbook
  syncPolicy:
    automated: {prune: true, selfHeal: true}   # the magic words
    syncOptions: [CreateNamespace=true]
```

```bash
$ kubectl apply -f app.yaml
$ kubectl get applications -n argocd
NAME        SYNC STATUS   HEALTH STATUS
guestbook   Synced        Healthy
$ kubectl get pods -n guestbook
guestbook-ui-56c646849b-vw62t   1/1     Running   0          90s

# THE GITOPS MOMENT — tamper with the cluster by hand, like a rogue admin:
$ kubectl scale deployment guestbook-ui -n guestbook --replicas=5
$ kubectl get deployment -n guestbook -w
guestbook-ui   5/5   5   5   4m
guestbook-ui   1/1   1   1   4m            # seconds later: Argo CD noticed the drift
                                             # and PUT IT BACK to match git. The cluster
                                             # now answers to the repo, not to you.
```

> **EXTEND IT** — Fork `argocd-example-apps` on GitHub, point `repoURL` at your fork, edit `guestbook/guestbook-ui-deployment.yaml` replicas in a commit — and watch the cluster follow your commit with no kubectl at all. Congratulations: deployment-by-pull-request, the way production platforms actually ship.

## Act 3 — kube-prometheus-stack

```bash
$ helm repo add prometheus-community https://prometheus-community.github.io/helm-charts && helm repo update
$ helm install monitoring prometheus-community/kube-prometheus-stack \
    -n monitoring --create-namespace --set grafana.adminPassword=practice
$ kubectl get pods -n monitoring
NAME                                                     READY   STATUS
alertmanager-monitoring-kube-prometheus-alertmanager-0   2/2     Running
monitoring-grafana-6b7d9c8f54-2kq8x                      3/3     Running
monitoring-kube-prometheus-operator-...                  1/1     Running
monitoring-kube-state-metrics-...                        1/1     Running
monitoring-prometheus-node-exporter-...  (one per node)  1/1     Running
prometheus-monitoring-kube-prometheus-prometheus-0       2/2     Running

$ kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
# Browser → http://localhost:3000 → admin / practice
# Preloaded dashboards worth an hour of exploration:
#   "Kubernetes / Compute Resources / Cluster"  — who is eating your VM
#   "Kubernetes / Compute Resources / Namespace (Pods)" — pick guestbook, watch it live
#   "Node Exporter / Nodes" — per-node pressure, straight from your Docker containers
```

## Act 4 — Close the loop: an alert you trigger on purpose

```bash
# Deploy a leaky app (limits it will inevitably hit):
$ kubectl create namespace leaky && kubectl apply -n leaky -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: leaker}
spec:
  replicas: 1
  selector: {matchLabels: {app: leaker}}
  template:
    metadata: {labels: {app: leaker}}
    spec:
      containers:
      - name: leaker
        image: python:3.12-alpine
        command: [python, -c, "l=[]\nwhile True: l.append(' ' * 10_000_000)"]
        resources:
          limits: {memory: 128Mi}
EOF
$ kubectl get pods -n leaky -w
leaker-...   0/1   OOMKilled   1 (10s ago)   30s
leaker-...   0/1   CrashLoopBackOff   2 (8s ago)    55s
# In Grafana: the namespace dashboard shows the sawtooth memory climb-and-kill.
# In Prometheus (port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090),
# query:  increase(kube_pod_container_status_restarts_total{namespace="leaky"}[10m])
# — and find the KubePodCrashLooping alert firing under Alerts. Metrics → dashboards
# → alerts: the full production observability loop, on your laptop.
```

## Cleanup

```bash
# Order matters: delete the Application FIRST — with selfHeal on, Argo CD would
# treat a deleted guestbook namespace as drift and resurrect it mid-cleanup:
$ kubectl delete application guestbook -n argocd
$ kubectl delete namespace guestbook leaky
$ kubectl delete namespace argocd
$ helm uninstall monitoring -n monitoring && kubectl delete namespace monitoring
```
