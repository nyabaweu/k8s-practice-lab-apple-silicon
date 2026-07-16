# Appendix — Scenario ↔ Concept Map & Quick Reference

| Scenario | Level | Core concepts exercised | Signature skill you walk away with |
|---|---|---|---|
| 1 — Hello, Cluster | Basic | Pod lifecycle, kubectl, labels, Deployments, Services | Reading the self-healing loop live; node-failure recovery |
| 2 — Config Kitchen | Basic | Resources, probes, ConfigMaps, Secrets, logs | Config-vs-restart semantics; probes that auto-heal deadlocks |
| 3 — Storage That Survives | Basic | Dynamic storage provisioning, CSI snapshots | Dynamic provisioning; snapshot → restore |
| 4 — Bookshelf | Medium | Deployments, Services, Ingress, HPA, rollouts | Three tiers + Ingress + HPA + zero-downtime rollout |
| 5 — Lock It Down | Medium | NetworkPolicies, RBAC, ServiceAccounts | Default-deny netpol; RBAC least-privilege with --as |
| 6 — Break It On Purpose | Medium | All the fundamentals, under diagnostic pressure | The describe→events→logs diagnostic reflex (CKA-style) |
| 7 — Nine-Node Fleet | Advanced | HA control plane, taints, spread, PDBs, chaos ops | Taints/spread/PDBs; surviving control-plane loss; etcd quorum |
| 8 — GitOps & Observability | Advanced | Helm, GitOps drift-correction, metrics→alerts loop | Argo CD drift-correction; Prometheus→Grafana→alert loop |
| 9 — Mini AI Platform | Advanced | Kueue queueing, batch Jobs, LLM serving, hybrid GPU | Kueue quotas/queueing; LLM serving; hybrid GPU architecture |

## Quick reference card

```bash
# ---- session ----
open -a Docker                                  # engine first
minikube start --profile=practice               # resume lab
minikube stop  --profile=practice               # pause lab (then quit Docker Desktop)
# ---- inspect ----
minikube status --profile=practice · k9s · minikube dashboard --profile=practice
kubectl get pods -A --field-selector=status.phase!=Running    # anything unhealthy?
# ---- reach apps ----
kubectl port-forward svc/NAME 8080:80 · minikube service NAME · minikube tunnel
# ---- reset ----
kubectl delete namespace NS                     # after each scenario
minikube delete --profile=practice              # nuclear; rebuild in ~3 min (§2.3–2.4)
```
