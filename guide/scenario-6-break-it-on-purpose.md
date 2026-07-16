# Scenario 6 — Break It On Purpose: Troubleshooting Drills

- **Goal** — Six pre-broken systems. For each: deploy the trap, read the symptom, find the cause with only `get`/`describe`/`logs`/`events`, fix it, verify. No peeking at the fault list until you've tried.
- **Time** — ~90 minutes (take two sittings)
- **Concepts** — Everything — this is the exam-muscle scenario. Format mirrors CKA troubleshooting tasks.

Work each drill the same way: `kubectl get pods` → what state? → `describe` → Events say? → `logs` if the container ran → form a theory → fix → verify. The faults are listed at the end of each drill upside-down style (in a callout) — resist reading ahead.

## Drill 1 — “It says Pending forever”

```bash
$ kubectl create namespace drills && kubectl config set-context --current --namespace=drills
$ kubectl apply -f - <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: drill1}
spec:
  replicas: 2
  selector: {matchLabels: {app: drill1}}
  template:
    metadata: {labels: {app: drill1}}
    spec:
      containers:
      - name: web
        image: nginx:1.27
        resources:
          requests: {cpu: "16", memory: 128Mi}
EOF
$ kubectl get pods
NAME                      READY   STATUS    RESTARTS   AGE
drill1-7b9f8d6c54-8jk2m   0/1     Pending   0          60s
drill1-7b9f8d6c54-x4vn9   0/1     Pending   0          60s
```

> **INVESTIGATE, THEN READ** — `describe pod` → Events: *“0/3 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }, 2 Insufficient cpu.”* Each pod requests **16 whole CPUs**; the entire Docker VM has 6 (remember §2.5: docker-driver nodes report the VM's full capacity, so the request must exceed the *VM* to be impossible). The scheduler isn't broken — the ask is. Fix: `kubectl set resources deployment drill1 --requests=cpu=100m` and watch both pods schedule.

## Drill 2 — “ImagePullBackOff”

```bash
$ kubectl create deployment drill2 --image=ngnix:1.27   # deploy exactly this
$ kubectl get pods
drill2-6d4b9c8f7-qq2zl   0/1     ImagePullBackOff   0     45s
```

> **INVESTIGATE, THEN READ** — Events: *“Failed to pull image "ngnix:1.27" … repository does not exist.”* Read the image name letter by letter: **ngnix**. The single most common outage cause there is — the image name is the field to be most careful with. Fix: `kubectl set image deployment/drill2 ngnix=nginx:1.27`.

## Drill 3 — “CrashLoopBackOff”

```bash
$ kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: {name: drill3}
spec:
  containers:
  - name: app
    image: postgres:17-alpine
EOF
$ kubectl get pods drill3
drill3   0/1     CrashLoopBackOff   3 (25s ago)   2m
```

> **INVESTIGATE, THEN READ** — `describe` shows restarts but not why. `kubectl logs drill3`: *“Error: Database is uninitialized and superuser password is not specified. You must specify POSTGRES_PASSWORD…”* — the container itself told you the fix. describe → then logs, always. Fix: delete and recreate with `env: [{name: POSTGRES_PASSWORD, value: drill}]` (or better, a Secret — Scenario 3 style).

## Drill 4 — “Service exists but nothing answers”

```bash
$ kubectl create deployment drill4 --image=nginx:1.27 --port=80
$ kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Service
metadata: {name: drill4}
spec:
  selector: {app: drill-4}
  ports: [{port: 80}]
EOF
$ kubectl run t --image=busybox --restart=Never --rm -it -- wget -T3 -qO- drill4
wget: download timed out
```

> **INVESTIGATE, THEN READ** — The service is fine; the pod is fine; check what binds them: `kubectl get endpointslices` → the drill4 slice has **no endpoints**. `kubectl describe svc drill4` → Selector: `app=drill-4`. The deployment's pods carry `app=drill4` — hyphen mismatch, so the service selects *nothing*. Labels are identity. Fix: `kubectl patch svc drill4 -p '{"spec":{"selector":{"app":"drill4"}}}'` and re-test. Empty EndpointSlice = selector mismatch, burn that reflex in.

## Drill 5 — “The mount that ate the app”

```bash
$ kubectl create configmap drill5-conf --from-literal=note.txt=hello
$ kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: {name: drill5}
spec:
  containers:
  - name: web
    image: nginx:1.27
    volumeMounts: [{name: conf, mountPath: /etc/nginx}]
  volumes: [{name: conf, configMap: {name: drill5-conf}}]
EOF
$ kubectl get pod drill5
drill5   0/1     CrashLoopBackOff   2 (18s ago)   80s
```

> **INVESTIGATE, THEN READ** — `kubectl logs drill5`: *“open() "/etc/nginx/nginx.conf" failed (2: No such file or directory)”*. A Kubernetes classic: mounting over an existing directory **obliterates it** — nginx's own config is gone. Fix with a subPath so the file coexists: `mountPath: /etc/nginx/note.txt` + `subPath: note.txt`.

## Drill 6 — “The quota says no”

```bash
# Clear the bench first — leftovers from drills 2–5 would count against the quota:
$ kubectl delete deployment drill2 drill4 && kubectl delete pod drill3 drill5 && kubectl delete svc drill4

$ kubectl create quota drill-quota --hard=pods=3,cpu=500m -n drills
$ kubectl scale deployment drill1 --replicas=5
$ kubectl get pods -l app=drill1
NAME                      READY   STATUS    AGE
drill1-5f6d7c8b9-2mkzq    1/1     Running   5m
drill1-5f6d7c8b9-8xw7l    1/1     Running   5m
drill1-5f6d7c8b9-pv4td    1/1     Running   5m       # …only 3 of 5. Where are the others?
```

> **INVESTIGATE, THEN READ** — Pods aren't Pending — they don't exist. Quota denials happen at *admission*, so look above the pod: `kubectl describe rs -l app=drill1` → Events: *“Error creating: pods "drill1-…" is forbidden: exceeded quota: drill-quota, requested: pods=1, used: pods=3, limited: pods=3.”* The bouncer at the club, caught red-handed. Also note the deployment shows `READY 3/5` — the desired-vs-actual gap is your alarm. Fix: raise the quota or lower the replicas.

## Cleanup

```bash
$ kubectl delete namespace drills && kubectl config set-context --current --namespace=default
```
