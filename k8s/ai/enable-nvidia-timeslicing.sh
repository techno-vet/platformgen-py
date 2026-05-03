#!/usr/bin/env bash
set -euo pipefail

kubectl apply -f - <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: nvidia-device-plugin-config
  namespace: kube-system
data:
  config.yaml: |
    version: v1
    sharing:
      timeSlicing:
        renameByDefault: false
        failRequestsGreaterThanOne: true
        resources:
          - name: nvidia.com/gpu
            replicas: 2
YAML

kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type='merge' -p \
  '{"spec":{"template":{"spec":{"runtimeClassName":"nvidia"}}}}'

python - <<'PY'
import json
import subprocess

raw = subprocess.check_output(
    ["kubectl", "-n", "kube-system", "get", "ds", "nvidia-device-plugin-daemonset", "-o", "json"],
    text=True,
)
obj = json.loads(raw)
container = obj["spec"]["template"]["spec"]["containers"][0]
patch = []

args = container.get("args")
if args != ["--config-file=/config/config.yaml"]:
    if args is None:
        patch.append({"op": "add", "path": "/spec/template/spec/containers/0/args", "value": ["--config-file=/config/config.yaml"]})
    else:
        patch.append({"op": "replace", "path": "/spec/template/spec/containers/0/args", "value": ["--config-file=/config/config.yaml"]})

if not any(vm.get("name") == "plugin-config" for vm in container.get("volumeMounts", [])):
    patch.append(
        {
            "op": "add",
            "path": "/spec/template/spec/containers/0/volumeMounts/-",
            "value": {"name": "plugin-config", "mountPath": "/config", "readOnly": True},
        }
    )

if not any(vol.get("name") == "plugin-config" for vol in obj["spec"]["template"]["spec"].get("volumes", [])):
    patch.append(
        {
            "op": "add",
            "path": "/spec/template/spec/volumes/-",
            "value": {"name": "plugin-config", "configMap": {"name": "nvidia-device-plugin-config"}},
        }
    )

if patch:
    subprocess.check_call(
        ["kubectl", "-n", "kube-system", "patch", "ds", "nvidia-device-plugin-daemonset", "--type=json", "-p", json.dumps(patch)]
    )
PY

kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=300s
kubectl get node -o jsonpath='{range .items[*]}{.metadata.name}{" capacity-gpu="}{.status.capacity.nvidia\.com/gpu}{" allocatable-gpu="}{.status.allocatable.nvidia\.com/gpu}{"\n"}{end}'
