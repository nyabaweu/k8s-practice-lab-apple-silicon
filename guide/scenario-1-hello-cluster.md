# Scenario 1 — Hello, Cluster: Deploy, Break, Self-Heal

- **Goal** — Deploy a real app, watch the scheduler spread it, then attack it and watch Kubernetes repair everything you break.
- **Time** — ~30 minutes
- **Concepts** — Pod lifecycle · kubectl · labels · Deployments · Services

## Act 1 — Deploy

```bash
$ kubectl create namespace hello
$ kubectl config set-context --current --namespace=hello   # stop typing -n hello everywhere

$ kubectl create deployment web --image=nginx:1.27 --replicas=4 --port=80
deployment.apps/web created

$ kubectl get pods -o wide
NAME                   READY   STATUS    RESTARTS   AGE   IP             NODE
web-7c9d6b58f4-4kzmq   1/1     Running   0          20s   10.244.120.4   practice-m02
web-7c9d6b58f4-8xw2l   1/1     Running   0          20s   10.244.151.3   practice-m03
web-7c9d6b58f4-pv9td   1/1     Running   0          20s   10.244.120.5   practice-m02
web-7c9d6b58f4-zn6rb   1/1     Running   0          20s   10.244.151.4   practice-m03
```

Read what the scheduler did: four pods, spread across both workers, none on the control plane — repelled by the taint we added in [setup §2.5](00-setup-and-operations.md#25-make-it-production-shaped-then-verify) — control-plane nodes stay free for cluster management. Now expose them:

```bash
$ kubectl expose deployment web --port=80
$ kubectl get svc,endpointslices
NAME          TYPE        CLUSTER-IP      PORT(S)
service/web   ClusterIP   10.109.44.183   80/TCP

NAME                 ADDRESSTYPE   PORTS   ENDPOINTS
web-x7k2p            IPv4          80      10.244.120.4,10.244.120.5,10.244.151.3 + 1 more
```

## Act 2 — Attack

Open a second terminal and put a live watch on the pods (or use k9s):

```bash
$ kubectl get pods -w          # terminal 2 — leave it running
```

```bash
# Attack ① — kill a pod:
$ kubectl delete pod web-7c9d6b58f4-4kzmq
# Terminal 2 shows the kill AND the replacement, within seconds:
web-7c9d6b58f4-4kzmq   1/1     Terminating   0     3m
web-7c9d6b58f4-hh5wd   0/1     Pending       0     0s
web-7c9d6b58f4-hh5wd   0/1     ContainerCreating   0     0s
web-7c9d6b58f4-hh5wd   1/1     Running       0     2s

# Attack ② — kill them ALL:
$ kubectl delete pods --all
# All four die; four replacements appear. The deployment's rule: exactly 4. No more, no less.

# Attack ③ — steal a pod's identity (the label-theft experiment, live):
$ kubectl label pod <any-web-pod> app-
$ kubectl get pods --show-labels
NAME                   ...   LABELS
web-7c9d6b58f4-hh5wd   ...   app=web,pod-template-hash=7c9d6b58f4
web-7c9d6b58f4-mm3fk   ...   pod-template-hash=7c9d6b58f4     ← the orphan: still running, unmanaged
web-7c9d6b58f4-q2v8x   ...   app=web,pod-template-hash=7c9d6b58f4
web-7c9d6b58f4-tt7lg   ...   app=web,pod-template-hash=7c9d6b58f4
web-7c9d6b58f4-wz4jn   ...   app=web,pod-template-hash=7c9d6b58f4   ← the replacement (now 5 pods!)
# Put the label back and watch the deployment delete one to get back to 4:
$ kubectl label pod web-7c9d6b58f4-mm3fk app=web
```

## Act 3 — Node failure (the real test)

```bash
# Simulate a node going dark — pause its container on the Docker side:
$ docker pause practice-m03
$ kubectl get nodes -w
practice-m03   NotReady   <none>   52m   v1.34.1     # after ~40s of missed heartbeats
# Wait ~5 minutes (the default eviction tolerance) and the pods on m03 are
# rescheduled to m02. Then heal the node:
$ docker unpause practice-m03
practice-m03   Ready      <none>   58m   v1.34.1
```

> **WHAT YOU JUST PROVED** — The three classic disasters of manual container management — dead containers, dead pods, dead node — repaired without you doing anything. That's the whole pitch of Kubernetes, demonstrated on your laptop.

## Cleanup

```bash
$ kubectl delete namespace hello
$ kubectl config set-context --current --namespace=default
```
