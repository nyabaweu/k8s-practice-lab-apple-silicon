# Scenario 2 — The Config Kitchen: ConfigMaps, Secrets & Probes

- **Goal** — Run one app three ways — hardcoded, configured, probed — and watch a liveness probe save you from a real hang.
- **Time** — ~45 minutes
- **Concepts** — Requests/limits · probes · statelessness · ConfigMaps · Secrets · logs

## Act 1 — A configurable app in 20 lines

```bash
$ kubectl create namespace kitchen && kubectl config set-context --current --namespace=kitchen

# kitchen-app.yaml — a tiny Python diner that reads its menu from the environment:
apiVersion: v1
kind: ConfigMap
metadata:
  name: menu
data:
  DISH_OF_DAY: "chocolate ice cream"     # a YAML classic
  GREETING: "Welcome to the Config Kitchen"
---
apiVersion: v1
kind: Secret
metadata:
  name: house-secret
stringData:
  SECRET_INGREDIENT: "cardamom"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: diner
spec:
  replicas: 2
  selector:
    matchLabels: {app: diner}
  template:
    metadata:
      labels: {app: diner}
    spec:
      containers:
      - name: diner
        image: python:3.12-alpine
        command: [python, -c]
        args:
        - |
          import http.server, os, json
          class H(http.server.BaseHTTPRequestHandler):
              def do_GET(self):
                  body = json.dumps({
                      "greeting": os.environ.get("GREETING","(unset)"),
                      "dish": os.environ.get("DISH_OF_DAY","(unset)"),
                      "secret_ingredient": os.environ.get("SECRET_INGREDIENT","(unset)"),
                      "pod": os.environ.get("HOSTNAME")}).encode()
                  self.send_response(200); self.end_headers(); self.wfile.write(body)
          http.server.HTTPServer(("",8080), H).serve_forever()
        envFrom:
        - configMapRef: {name: menu}
        - secretRef: {name: house-secret}
        resources:
          requests: {cpu: 50m, memory: 64Mi}
          limits: {cpu: 250m, memory: 128Mi}
```

```bash
$ kubectl apply -f kitchen-app.yaml
$ kubectl expose deployment diner --port=80 --target-port=8080
$ kubectl run taster --image=busybox --restart=Never --rm -it -- wget -qO- diner
{"greeting": "Welcome to the Config Kitchen", "dish": "chocolate ice cream",
 "secret_ingredient": "cardamom", "pod": "diner-6f8b9c7d55-k2xwq"}
```

## Act 2 — Change config without touching the app

```bash
$ kubectl patch configmap menu -p '{"data":{"DISH_OF_DAY":"mango sticky rice"}}'
$ kubectl run taster --image=busybox --restart=Never --rm -it -- wget -qO- diner
... "dish": "chocolate ice cream" ...       # STILL the old dish! Why?
```

> **THE LESSON HIDING HERE** — Env vars from a ConfigMap are read *once, at container start*. The ConfigMap changed; the running containers didn't. Fix: restart the pods — `kubectl rollout restart deployment diner` — and taste again: `"dish": "mango sticky rice"`. This “why is my config change not applying?!” moment is one of the most common real-world confusions; you've now debugged it on purpose.

## Act 3 — Probes that earn their keep

Add an endpoint that lets you *hang* the app on demand, plus a liveness probe. Replace the deployment's args with this extended version and add the probe:

```bash
args:
        - |
          import http.server, os, json, time
          WEDGED = {"v": False}
          class H(http.server.BaseHTTPRequestHandler):
              def do_GET(self):
                  if self.path == "/wedge": WEDGED["v"] = True
                  if WEDGED["v"]: time.sleep(3600)          # simulate a deadlocked app
                  self.send_response(200); self.end_headers()
                  self.wfile.write(json.dumps({"ok": True,
                      "pod": os.environ.get("HOSTNAME")}).encode())
          http.server.HTTPServer(("",8080), H).serve_forever()
        livenessProbe:
          httpGet: {path: /healthz, port: 8080}
          initialDelaySeconds: 3
          periodSeconds: 5
          timeoutSeconds: 1
          failureThreshold: 3
```

```bash
$ kubectl apply -f kitchen-app.yaml && kubectl rollout status deploy/diner
# Wedge one pod through the service, then watch:
$ kubectl run wedger --image=busybox --restart=Never --rm -it -- wget -qO- -T 2 diner/wedge
wget: download timed out                    # expected — the pod is now hung forever
$ kubectl get pods -w
diner-59d7f6c9b8-k2xwq   1/1   Running   0             4m
diner-59d7f6c9b8-k2xwq   1/1   Running   1 (2s ago)    4m   # RESTARTS: 0 → 1
```

Do the math against the probe settings: hang at t=0; probes fail at ~5, ~10, ~15 s (each timing out after 1 s); third consecutive strike → kubelet kills and restarts the container. Total ~16–18 seconds from deadlock to recovery, *no human involved*. Check the evidence trail:

```bash
$ kubectl describe pod diner-59d7f6c9b8-k2xwq | grep -A3 Events
Events:
  Warning  Unhealthy  61s (x3 over 71s)  kubelet  Liveness probe failed: ... context deadline exceeded
  Normal   Killing    61s                kubelet  Container diner failed liveness probe, will be restarted
```

## Cleanup

```bash
$ kubectl delete namespace kitchen && kubectl config set-context --current --namespace=default
```
