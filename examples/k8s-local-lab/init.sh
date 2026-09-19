# Load into bash/zsh: source ./init.sh
_lab_init() {
  local lab_source lab_root
  if [ -n "${ZSH_VERSION:-}" ]; then
    eval 'lab_source=${(%):-%x}'
  else
    lab_source="${BASH_SOURCE[0]}"
  fi
  lab_root="$(cd -- "$(dirname -- "$lab_source")" && pwd)" || return
  # Resolve paths before running setup; exports happen only after success.
  python3 "$lab_root/setup.py" || return
  export PATH="$lab_root/bin:$lab_root/runtime/bin:$PATH"
  export KUBECONFIG="$lab_root/kubeconfig"
  export DOCKER_CONTEXT=colima-learning-lab
  unset DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH
  printf '%s\n' '环境已加载：kubectl get pods；Docker 使用 Colima learning-lab。'
}
_lab_init
