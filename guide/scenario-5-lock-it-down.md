# Scenario 5 — Lock It Down: NetworkPolicies & RBAC

- **Goal** — Take Bookshelf from “peace and love” to zero-trust: default-deny networking with surgical allows, then a developer identity that can see but not touch.
- **Time** — ~60 minutes
- **Concepts** — NetworkPolicies · RBAC & ServiceAccounts
- **Prereq** — Scenario 4 deployed (or redeploy its Acts 1–3 quickly — good revision anyway).

## Act 1 — Prove the problem

```bash
$ kubectl create namespace intruder
$ kubectl run spy -n intruder --image=busybox --restart=Never --rm -it -- \
    sh -c "wget -qO- api.bookshelf/api/books | head -c 50"
[{"author":"Kim","title":"The Phoenix Project"},{"auth
# A pod in a DIFFERENT namespace just read your API — and could reach postgres
# on 5432 too. Everybody can talk to everybody. Peace and love; security nightmare.
```

## Act 2 — Default deny, then earn each connection back

```yaml
# lockdown.yaml — three policies that express the app's real contract:
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny, namespace: bookshelf}
spec:
  podSelector: {}
  policyTypes: [Ingress]        # ingress-only deny: pods can still reach DNS/outward
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: db-from-api-only, namespace: bookshelf}
spec:
  podSelector: {matchLabels: {app: postgres}}
  policyTypes: [Ingress]
  ingress:
  - from: [{podSelector: {matchLabels: {app: api}}}]
    ports: [{protocol: TCP, port: 5432}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: api-from-frontend-and-ingress, namespace: bookshelf}
spec:
  podSelector: {matchLabels: {app: api}}
  policyTypes: [Ingress]
  ingress:
  - from:
    - podSelector: {matchLabels: {app: frontend}}
    - namespaceSelector:          # the ingress controller lives in ANOTHER namespace —
        matchLabels:               # without this clause, bookshelf.local/api goes dark
          kubernetes.io/metadata.name: ingress-nginx
    ports: [{protocol: TCP, port: 8080}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy          # don't forget the UI itself — the browser path enters
                              # through the ingress controller too:
metadata: {name: frontend-from-ingress, namespace: bookshelf}
spec:
  podSelector: {matchLabels: {app: frontend}}
  policyTypes: [Ingress]
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports: [{protocol: TCP, port: 80}]
```

```bash
$ kubectl apply -f lockdown.yaml
# Re-run the spy:
$ kubectl run spy -n intruder --image=busybox --restart=Never --rm -it -- \
    sh -c "wget -T 3 -qO- api.bookshelf/api/books"
wget: download timed out                    # denied. Calico is earning its keep.
# But the legitimate paths still work:
$ curl -s bookshelf.local/api/books | head -c 30
[{"author":"Kim","title":"The 
# And http://bookshelf.local still loads in the browser (the frontend policy).
# Frontend → api: allowed. Ingress → api and → frontend: allowed. intruder → api: dead.
# api → db: allowed. spy → db: try it — dead. The contract is now enforced, not implied.
```

## Act 3 — RBAC: the read-only developer

```bash
$ kubectl create serviceaccount dev-viewer -n bookshelf
$ kubectl create role viewer -n bookshelf \
    --verb=get,list,watch --resource=pods,services,deployments,configmaps
$ kubectl create rolebinding dev-viewer-binding -n bookshelf \
    --role=viewer --serviceaccount=bookshelf:dev-viewer

# Now impersonate that identity — no second laptop needed:
$ kubectl auth can-i list pods -n bookshelf --as=system:serviceaccount:bookshelf:dev-viewer
yes
$ kubectl auth can-i delete pods -n bookshelf --as=system:serviceaccount:bookshelf:dev-viewer
no
$ kubectl auth can-i list pods -n default --as=system:serviceaccount:bookshelf:dev-viewer
no                                          # Role ≠ ClusterRole: powers end at the namespace wall
$ kubectl delete deployment api -n bookshelf --as=system:serviceaccount:bookshelf:dev-viewer
Error from server (Forbidden): deployments.apps "api" is forbidden: User
"system:serviceaccount:bookshelf:dev-viewer" cannot delete resource "deployments" ...
# Read the error like a sentence: WHO cannot do WHAT to WHICH resource WHERE.
# You'll see this exact grammar in production incidents; now it's an old friend.
```

## Cleanup

```bash
$ kubectl delete namespace bookshelf intruder
$ kubectl config set-context --current --namespace=default
$ sudo sed -i '' '/bookshelf.local/d' /etc/hosts
```
