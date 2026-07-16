# Scenario 3 — Storage That Survives: PVCs, a Database & Snapshots

- **Goal** — Run PostgreSQL with a real PVC, destroy the pod and keep the data, then take a CSI snapshot and restore from it — the full storage lifecycle.
- **Time** — ~45 minutes
- **Concepts** — StorageClass → PV → PVC · Secrets · snapshots · StatefulSets preview

## Act 1 — Dynamic provisioning (what manual PV provisioning grows up into)

```bash
$ kubectl create namespace vault && kubectl config set-context --current --namespace=vault
$ kubectl get storageclass
NAME                 PROVISIONER              RECLAIMPOLICY   VOLUMEBINDINGMODE
csi-hostpath-sc      hostpath.csi.k8s.io      Delete          Immediate
standard (default)   k8s.io/minikube-hostpath Delete          Immediate
```

```yaml
# postgres.yaml — Secret + PVC + Deployment (note: csi-hostpath-sc, snapshot-capable):
apiVersion: v1
kind: Secret
metadata: {name: pg-secret}
stringData: {POSTGRES_PASSWORD: practice123}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: pg-data}
spec:
  storageClassName: csi-hostpath-sc
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 2Gi}}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: postgres}
spec:
  replicas: 1
  strategy: {type: Recreate}     # RWO volume: never two pods at once during updates
  selector: {matchLabels: {app: postgres}}
  template:
    metadata: {labels: {app: postgres}}
    spec:
      containers:
      - name: postgres
        image: postgres:17-alpine
        envFrom: [{secretRef: {name: pg-secret}}]
        env: [{name: PGDATA, value: /var/lib/postgresql/data/pgdata}]
        ports: [{containerPort: 5432}]
        volumeMounts: [{name: data, mountPath: /var/lib/postgresql/data}]
      volumes:
      - name: data
        persistentVolumeClaim: {claimName: pg-data}
```

```bash
$ kubectl apply -f postgres.yaml
$ kubectl get pvc,pv
NAME                            STATUS   VOLUME         CAPACITY   ACCESS MODES   STORAGECLASS
persistentvolumeclaim/pg-data   Bound    pvc-8a1f3c2e   2Gi        RWO            csi-hostpath-sc

NAME                            CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM
persistentvolume/pvc-8a1f3c2e   2Gi        RWO            Delete           Bound    vault/pg-data
# Notice: you wrote NO PersistentVolume. The CSI driver minted one on demand —
# dynamic provisioning, the grown-up version of hand-writing PersistentVolumes.
```

## Act 2 — Write data, murder the pod, data survives

```bash
$ kubectl exec -it deploy/postgres -- psql -U postgres -c \
  "CREATE TABLE heroes(name text); INSERT INTO heroes VALUES ('Superman'),('Batman'),('Wonder Woman'),('Flash');"
INSERT 0 4

$ kubectl delete pod -l app=postgres       # murder
$ kubectl get pods -w                       # wait for the replacement to be 1/1 Running
$ kubectl exec -it deploy/postgres -- psql -U postgres -c "SELECT * FROM heroes;"
     name
--------------
 Superman
 Batman
 Wonder Woman
 Flash
(4 rows)                                   # new pod, same data — the PVC did its job
```

## Act 3 — Snapshot, disaster, restore

```yaml
# snapshot.yaml:
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata: {name: pg-snap-1}
spec:
  volumeSnapshotClassName: csi-hostpath-snapclass
  source: {persistentVolumeClaimName: pg-data}
```

```bash
$ kubectl apply -f snapshot.yaml && kubectl get volumesnapshot
NAME        READYTOUSE   SOURCEPVC   RESTORESIZE   AGE
pg-snap-1   true         pg-data     2Gi           10s

# Now the "disaster" — an intern with prod access:
$ kubectl exec -it deploy/postgres -- psql -U postgres -c "DROP TABLE heroes;"
DROP TABLE

# Restore: a NEW PVC born from the snapshot, then point postgres at it —
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: pg-data-restored}
spec:
  storageClassName: csi-hostpath-sc
  dataSource:
    name: pg-snap-1
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteOnce]
  resources: {requests: {storage: 2Gi}}
```

```bash
# Edit postgres.yaml: claimName: pg-data → pg-data-restored, then:
$ kubectl apply -f pg-restore-pvc.yaml && kubectl apply -f postgres.yaml
$ kubectl exec -it deploy/postgres -- psql -U postgres -c "SELECT count(*) FROM heroes;"
 count
-------
     4                                     # the table is back. You just ran a
                                             # point-in-time restore, on a laptop.
```

> **STRETCH GOAL** — Rewrite the postgres Deployment as a **StatefulSet** with a `volumeClaimTemplates` block and a headless Service — then scale it to 2 and inspect what's different about the pod names, DNS records, and the second PVC that appears. That's the StatefulSet model, made real.

## Cleanup

```bash
$ kubectl delete namespace vault && kubectl config set-context --current --namespace=default
$ kubectl get pv    # confirm the dynamic PVs were reclaimed (Delete policy)
```
