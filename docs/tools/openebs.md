# OpenEBS

OpenEBS provides the `openebs-hostpath` StorageClass. The SUE's Prometheus and the Elasticsearch volume both request it.

| | |
|---|---|
| Chart | `openebs/openebs` |
| Version | 4.6.2 |
| Release and namespace | `openebs` in `openebs` |
| Installed by | `oxn setup`, once per cluster |

Skip this page if the StorageClass already exists:

```bash
kubectl get storageclass openebs-hostpath
```

## Deploy with Helm

```bash
helm repo add openebs https://openebs.github.io/openebs
helm repo update

helm upgrade --install openebs openebs/openebs \
    --namespace openebs \
    --create-namespace \
    --version 4.6.2 \
    --set engines.local.lvm.enabled=false \
    --set engines.local.zfs.enabled=false \
    --set engines.replicated.mayastor.enabled=false \
    --set loki.enabled=false \
    --set alloy.enabled=false \
    --set localpv-provisioner.hostpathClass.isDefaultClass=true
```

The options leave only the hostpath engine, which is all GOXN needs. By default the chart also installs the LVM, ZFS and Mayastor engines, plus Loki, MinIO and Alloy. The last option makes `openebs-hostpath` the cluster's default StorageClass.

The 3.x charts lived in the older repository `https://openebs.github.io/charts`, which stops at 3.10.0.

## Using another engine

If the cluster uses another engine, such as LVM, `openebs-hostpath` does not exist and the charts' volumes stay pending. `oxn setup` reports this as a conflict and leaves the install alone, because upgrading with the options above would turn the other engine off. Create a StorageClass named `openebs-hostpath` yourself that uses the engine's provisioner.

## Check it

```bash
kubectl get pods -n openebs
kubectl get storageclass openebs-hostpath
```

## Remove it

Other tools depend on this StorageClass, so remove their volumes first.

```bash
helm uninstall openebs --namespace openebs
```
