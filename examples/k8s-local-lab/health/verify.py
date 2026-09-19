import json
import subprocess
import time
from pathlib import Path
R=Path(__file__).resolve().parents[1]
K=[str(R/'bin/kubectl'),'--kubeconfig',str(R/'kubeconfig'),'--context','kind-resource-lab','-n','resource-lab']
def k(*args,data=None):
 return subprocess.check_output(K+list(args),input=data,text=True,timeout=30)
def pod():
 items=json.loads(k('get','pods','-l','app=health-demo','-o','json'))['items']
 return next((p for p in items if not p['metadata'].get('deletionTimestamp')),None)
def ready(p):return p and any(c['type']=='Ready' and c['status']=='True' for c in p['status'].get('conditions',[]))
def wait(test):
 end=time.monotonic()+90
 while time.monotonic()<end:
  p=pod()
  if test(p):return p
  time.sleep(1)
 raise RuntimeError('Health check timed out')
def restarts(p):return p['status']['containerStatuses'][0]['restartCount']
cm={'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'health-code','namespace':'resource-lab'},'data':{'worker.py':(R/'health/worker.py').read_text()}}
k('apply','-f','-',data=json.dumps(cm));k('apply','-f',str(R/'health/deployment.yaml'))
a=wait(ready);name=a['metadata']['name'];uid=a['metadata']['uid'];n=restarts(a)
# Reset previous manual fault injection, then observe readiness transitions.
k('exec',name,'--','touch','/tmp/live','/tmp/ready')
a=wait(ready);n=restarts(a)
k('exec',name,'--','rm','/tmp/ready')
b=wait(lambda p:p and not ready(p));assert b['metadata']['uid']==uid and restarts(b)==n
slices=json.loads(k('get','endpointslices','-l','kubernetes.io/service-name=health-demo','-o','json'))
# Endpoint controller convergence is asynchronous; wait for its view too.
end=time.monotonic()+30
while True:
 slices=json.loads(k('get','endpointslices','-l','kubernetes.io/service-name=health-demo','-o','json'))
 eps=[e for i in slices['items'] for e in i.get('endpoints',[])]
 if eps and all(e.get('conditions',{}).get('ready') is False for e in eps):break
 if time.monotonic()>end:raise RuntimeError('EndpointSlice did not become unready')
 time.sleep(1)
k('exec',name,'--','touch','/tmp/ready');wait(ready)
print('PASS readiness: Ready false -> true, same Pod UID, no restart; endpoint became unready',flush=True)
k('exec',name,'--','rm','/tmp/live')
c=wait(lambda p:ready(p) and restarts(p)>n);assert c['metadata']['uid']==uid
print('PASS liveness: same Pod UID, restartCount increased',flush=True)
k('delete','pod',name,'--wait=false')
d=wait(lambda p:ready(p) and p['metadata']['uid']!=uid)
print('PASS ReplicaSet: deleted Pod replaced by a new UID',flush=True)
(R/'results').mkdir(exist_ok=True)
(R/'results/health-summary.json').write_text(json.dumps({'before':a,'unready':b,'endpoints_unready':slices,'restarted':c,'replacement':d},indent=2))
