"""Prepare a dedicated Colima + kind environment. Never launches Docker Desktop."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
BIN = ROOT / 'bin'
BIN.mkdir(exist_ok=True)
ENV = os.environ.copy()
ENV['PATH'] = str(BIN) + ':' + str(ROOT / 'runtime/bin') + ':' + ENV.get('PATH', '')
ENV['DOCKER_CONTEXT'] = 'colima-learning-lab'
for key in ['DOCKER_HOST', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH']:
    ENV.pop(key, None)
NODE = 'kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5'

def run(args, capture=False, check=True):
    return subprocess.run(args, env=ENV, cwd=ROOT, text=True, capture_output=capture, check=check)

def download_tool(name, url, checksum_url):
    target = BIN / name
    if target.exists():
        return
    tmp = target.with_suffix('.download')
    run(['curl', '-fLsS', '--retry', '2', '--max-time', '180', '-o', str(tmp), url])
    expected = urllib.request.urlopen(checksum_url, timeout=30).read().decode().split()[0]
    if hashlib.sha256(tmp.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Checksum mismatch: ' + name)
    tmp.chmod(0o755)
    tmp.replace(target)

if platform.system() != 'Darwin':
    sys.exit('本初始化脚本面向 macOS。')
for tool in ['colima', 'docker']:
    if not shutil.which(tool, path=ENV['PATH']):
        sys.exit('缺少 ' + tool + '。先用 Homebrew 安装：brew install colima docker')
arm = subprocess.run(['sysctl', '-n', 'hw.optional.arm64'], capture_output=True, text=True).stdout.strip() == '1'
arch = 'arm64' if arm else 'amd64'
download_tool('kind', f'https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-darwin-{arch}',
              f'https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-darwin-{arch}.sha256sum')
download_tool('kubectl', f'https://dl.k8s.io/release/v1.37.0/bin/darwin/{arch}/kubectl',
              f'https://dl.k8s.io/release/v1.37.0/bin/darwin/{arch}/kubectl.sha256')
status = run(['colima', 'status', '--profile', 'learning-lab'], capture=True, check=False)
if status.returncode:
    run(['colima', 'start', '--profile', 'learning-lab', '--runtime', 'docker', '--vm-type', 'vz',
         '--cpu', '4', '--memory', '6', '--disk', '30', '--activate=false'])
run(['docker', 'info', '--format', 'Colima Docker {{.ServerVersion}}; CPU={{.NCPU}}; Memory={{.MemTotal}}'])
clusters = run(['kind', 'get', 'clusters'], capture=True).stdout.split()
if 'resource-lab' not in clusters:
    run(['kind', 'create', 'cluster', '--name', 'resource-lab', '--config', str(ROOT/'kind.yaml'),
         '--kubeconfig', str(ROOT/'kubeconfig'), '--image', NODE, '--wait', '120s'])
else:
    # Resume this named kind node if the VM was stopped while it existed.
    run(['docker', 'start', 'resource-lab-control-plane'], capture=True)
    run(['kind', 'export', 'kubeconfig', '--name', 'resource-lab', '--kubeconfig', str(ROOT/'kubeconfig')])
K = ['kubectl', '--kubeconfig', str(ROOT/'kubeconfig'), '--context', 'kind-resource-lab']
run(K + ['wait', '--for=condition=Ready', 'node', '--all', '--timeout=120s'])
ns = {'apiVersion':'v1','kind':'Namespace','metadata':{'name':'resource-lab'}}
subprocess.run(K + ['apply','-f','-'], input=json.dumps(ns), text=True, env=ENV, check=True)
run(K + ['config','set-context','kind-resource-lab','--namespace=resource-lab'])
# Loading through the host CLI also works when node registry proxy access is unavailable.
image = 'python:3.12-alpine'
if run(['docker','image','inspect',image],capture=True,check=False).returncode:
    run(['docker','pull',image])
# Import only the host platform: Docker 29 exports an OCI index whose other
# platform manifests may be absent; kind's --all-platforms import then fails.
node_images = run(['docker','exec','resource-lab-control-plane','ctr','--namespace=k8s.io','images','list','-q'], capture=True).stdout.split()
if 'docker.io/library/' + image not in node_images:
    with tempfile.TemporaryFile() as archive:
        subprocess.run(['docker','save',image], stdout=archive, env=ENV, check=True)
        archive.seek(0)
        subprocess.run(['docker','exec','-i','resource-lab-control-plane','ctr','--namespace=k8s.io',
                        'images','import','--platform','linux/'+arch,'--snapshotter=overlayfs','-'],
                       stdin=archive, env=ENV, check=True)
run(K + ['get','nodes'])
