import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
K = [str(ROOT / 'bin/kubectl'), '--kubeconfig', str(ROOT / 'kubeconfig'), '--context', 'kind-resource-lab']
OUT = ROOT / 'results'
OUT.mkdir(exist_ok=True)

def k(*args, data=None):
    p = subprocess.run(K + list(args), input=data, text=True, capture_output=True, timeout=30)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return p.stdout

def apply(obj):
    return k('apply', '-f', '-', data=json.dumps(obj))

apply({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': 'resource-lab'}})
apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'workload', 'namespace': 'resource-lab'},
       'data': {'workload.py': (ROOT / 'workload.py').read_text()}})
results = {}
for name, mode, cpu, memory in [('cpu-250m', 'cpu', '250m', '64Mi'), ('cpu-1000m', 'cpu', '1', '64Mi'),
                                ('memory-64mi', 'memory', '500m', '64Mi'), ('memory-256mi', 'memory', '500m', '256Mi')]:
    # Only replace this lab's named experiment Pod when rerunning.
    k('-n', 'resource-lab', 'delete', 'pod', name, '--ignore-not-found', '--wait=true', '--timeout=20s')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': 'resource-lab', 'labels': {'app': 'resource-lab'}},
           'spec': {'restartPolicy': 'Never', 'activeDeadlineSeconds': 180,
                    'containers': [{'name': 'worker', 'image': 'python:3.12-alpine', 'command': ['python', '-u', '/lab/workload.py'],
                                    'env': [{'name': 'MODE', 'value': mode}],
                                    'resources': {'requests': {'cpu': '100m', 'memory': '32Mi'}, 'limits': {'cpu': cpu, 'memory': memory}},
                                    'volumeMounts': [{'name': 'code', 'mountPath': '/lab', 'readOnly': True}]}],
                    'volumes': [{'name': 'code', 'configMap': {'name': 'workload'}}]}}
    (ROOT / (name + '.json')).write_text(json.dumps(pod, indent=2))
    apply(pod)
    deadline = time.monotonic() + 200
    while True:
        status = json.loads(k('-n', 'resource-lab', 'get', 'pod', name, '-o', 'json'))
        if status['status']['phase'] in ('Succeeded', 'Failed'):
            break
        if time.monotonic() > deadline:
            raise RuntimeError(f'{name}: timed out; inspect Pod events')
        time.sleep(2)
    log = k('-n', 'resource-lab', 'logs', name)
    (OUT / (name + '.log')).write_text(log)
    (OUT / (name + '.json')).write_text(json.dumps(status, indent=2))
    terminated = status['status']['containerStatuses'][0]['state'].get('terminated', {})
    records = [json.loads(line) for line in log.splitlines() if line.startswith('{')]
    results[name] = {'phase': status['status']['phase'], 'reason': terminated.get('reason'),
                     'exitCode': terminated.get('exitCode'), 'records': records}
    print(name, results[name]['reason'], records[-1] if records else '', flush=True)
(OUT / 'summary.json').write_text(json.dumps(results, indent=2))
assert results['memory-64mi']['reason'] == 'OOMKilled', '64Mi should OOM'
assert results['memory-256mi']['reason'] == 'Completed', '256Mi should complete'
for name, expected in [('cpu-250m', 0.25), ('cpu-1000m', 1)]:
    measured = results[name]['records'][-1]['average_cpu_cores']
    assert results[name]['reason'] == 'Completed'
    assert measured < expected * 1.2, f'{name}: CPU limit not observed'
    quota, period = map(int, results[name]['records'][0]['cpu.max'].split())
    assert quota / period == expected, f'{name}: wrong cgroup quota'
    if expected == 0.25:
        record = results[name]['records'][-1]
        before = dict(line.split() for line in record['cpu_stat_before'].splitlines())
        after = dict(line.split() for line in record['cpu_stat_after'].splitlines())
        assert int(after['nr_throttled']) > int(before['nr_throttled']), 'Expected CPU throttling'
print('Resource limit checks passed; inspect results/summary.json for actual measurements.', flush=True)
