#!/usr/bin/env bash
# Install Wave-1 capability-shared plugin venvs (YOLO / TFLM / RAG).
#
# Creates isolated venvs OUTSIDE the API image (or into GRAPHYN_PLUGIN_VENVS_DIR
# / a Docker volume) and symlinks plugin slugs so Graphyn's isolated runtime
# finds them under {GRAPHYN_PLUGIN_VENVS_DIR}/<plugin-name>/bin/python.
#
# Usage:
#   ./scripts/install_wave1_plugin_venvs.sh              # all capabilities
#   ./scripts/install_wave1_plugin_venvs.sh vision rag   # subset
#   GRAPHYN_WAVE1_TORCH=cpu ./scripts/install_wave1_plugin_venvs.sh
#
# Env:
#   GRAPHYN_WAVE1_VENVS_ROOT   default: $GRAPHYN_PLUGIN_VENVS_DIR or
#                              $GRAPHYN_HOME/plugins/venvs or ./.graphyn/plugins/venvs
#   GRAPHYN_WAVE1_TORCH        cpu (default) | cuda
#                              Prefer cpu when FaceRecognition / other apps hold GPU.
#   GRAPHYN_WAVE1_PYTHON       python binary (default: python3)
#   GRAPHYN_WAVE1_SKIP_SYMLINK 1 to skip plugin-name symlinks
#   PIP_INDEX_URL / PIP_EXTRA_INDEX_URL  optional mirrors
#
# After install, export (or set in docker-compose):
#   GRAPHYN_WAVE1_VENV_VISION=$ROOT/wave1-vision
#   GRAPHYN_WAVE1_VENV_TINYML=$ROOT/wave1-tinyml
#   GRAPHYN_WAVE1_VENV_RAG=$ROOT/wave1-rag
#   GRAPHYN_ISOLATED_INSTALL_TORCH=1   # if API boot should also pip torch
#   GRAPHYN_ISOLATED_INSTALL_ALL_OPTIONAL=1  # optional: install all optionals at load
#
# Does NOT touch FaceRecognition or steal GPU (CPU torch by default).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

log() { printf 'wave1-venv: %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

PYTHON_BIN="${GRAPHYN_WAVE1_PYTHON:-python3}"
TORCH_FLAVOR="${GRAPHYN_WAVE1_TORCH:-cpu}"
SKIP_SYMLINK="${GRAPHYN_WAVE1_SKIP_SYMLINK:-0}"

if [[ -n "${GRAPHYN_WAVE1_VENVS_ROOT:-}" ]]; then
  ROOT="$GRAPHYN_WAVE1_VENVS_ROOT"
elif [[ -n "${GRAPHYN_PLUGIN_VENVS_DIR:-}" ]]; then
  ROOT="$GRAPHYN_PLUGIN_VENVS_DIR"
elif [[ -n "${GRAPHYN_HOME:-}" ]]; then
  ROOT="$GRAPHYN_HOME/plugins/venvs"
else
  ROOT="$REPO_ROOT/.graphyn/plugins/venvs"
fi
ROOT="$(mkdir -p "$ROOT" && cd "$ROOT" && pwd)"
log "venvs root: $ROOT"
log "python: $PYTHON_BIN ($($PYTHON_BIN --version 2>&1))"
log "torch flavor: $TORCH_FLAVOR"

# Disk sanity (need ~6–8 GiB free for all three).
avail_kb="$(df -Pk "$ROOT" | awk 'NR==2{print $4}')"
if [[ -n "$avail_kb" && "$avail_kb" -lt 4000000 ]]; then
  log "WARNING: only ~$((avail_kb/1024)) MiB free under $ROOT — install may fail"
fi

# Capability → packages (PEP 508). Torch handled separately for CPU/CUDA index.
declare -A CAP_PKGS=(
  [vision]="ultralytics>=8.0 torchvision numpy>=1.24 opencv-python-headless>=4.8 pillow>=10.0"
  [tinyml]="tensorflow>=2.13 numpy>=1.24"
  [rag]="chromadb>=0.4 faiss-cpu>=1.7 sentence-transformers>=2.2 numpy>=1.24"
)

declare -A CAP_PLUGINS=(
  [vision]="yolo-train yolo-predict yolo-val yolo-export yolo-track yolo-resume-train yolo-hyperparam-search yolo-task-detect yolo-task-segment yolo-task-pose yolo-task-obb-classify"
  [tinyml]="tflm-quantize tflm-convert tflm-host-sim tflm-op-support-check tinyml-ptq-calib-builder"
  [rag]="vector-store-write vector-store-query text-embed chunk-semantic multimodal-caption-embed"
)

ALL_CAPS=(vision tinyml rag)
CAPS=("$@")
if [[ ${#CAPS[@]} -eq 0 ]]; then
  CAPS=("${ALL_CAPS[@]}")
fi

pip_install() {
  local py="$1"; shift
  "$py" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$py" -m pip install "$@"
}

install_torch() {
  local py="$1"
  if [[ "$TORCH_FLAVOR" == "cuda" ]]; then
    log "installing torch+torchvision (CUDA default index)…"
    pip_install "$py" "torch>=2.0" "torchvision"
  else
    log "installing torch+torchvision CPU wheels (FaceRecognition-safe)…"
    # Official CPU wheel index; keep torch/torchvision matched.
    if ! pip_install "$py" --index-url https://download.pytorch.org/whl/cpu "torch>=2.0" "torchvision"; then
      log "CPU index failed; falling back to default torch/torchvision pins (may pull CUDA)"
      pip_install "$py" "torch>=2.0" "torchvision"
    fi
  fi
}

create_capability() {
  local cap="$1"
  local venv_dir="$ROOT/wave1-$cap"
  local py="$venv_dir/bin/python"
  local pkgs="${CAP_PKGS[$cap]:-}"
  [[ -n "$pkgs" ]] || die "unknown capability: $cap"

  if [[ ! -x "$py" ]]; then
    log "creating venv $venv_dir"
    "$PYTHON_BIN" -m venv "$venv_dir"
  else
    log "reusing venv $venv_dir"
  fi

  # Bootstrap imports used by Graphyn isolated workers (numpy always).
  pip_install "$py" "numpy>=1.24"

  case "$cap" in
    vision|rag)
      install_torch "$py"
      ;;
  esac

  # shellcheck disable=SC2086
  log "installing $cap packages: $pkgs"
  pip_install "$py" $pkgs

  # Sanity probes
  case "$cap" in
    vision)
      "$py" -c "import torch, ultralytics; print('vision OK', torch.__version__, ultralytics.__version__, 'cuda', torch.cuda.is_available())"
      ;;
    tinyml)
      "$py" -c "import tensorflow as tf; print('tinyml OK', tf.__version__)"
      ;;
    rag)
      "$py" -c "import chromadb, faiss, sentence_transformers; print('rag OK', chromadb.__version__)"
      ;;
  esac

  # Marker for tests / ops
  {
    echo "capability=$cap"
    echo "created=$(date -Iseconds)"
    echo "torch_flavor=$TORCH_FLAVOR"
    echo "python=$($py -c 'import sys; print(sys.executable)')"
  } > "$venv_dir/wave1.marker"

  if [[ "$SKIP_SYMLINK" != "1" ]]; then
    local plugin
    for plugin in ${CAP_PLUGINS[$cap]}; do
      local link="$ROOT/$plugin"
      if [[ -e "$link" && ! -L "$link" ]]; then
        log "skip symlink $plugin — real directory already exists"
        continue
      fi
      ln -sfn "wave1-$cap" "$link"
      log "symlink $plugin -> wave1-$cap"
    done
  fi

  # Export helper snippet
  local env_key
  case "$cap" in
    vision) env_key=GRAPHYN_WAVE1_VENV_VISION ;;
    tinyml) env_key=GRAPHYN_WAVE1_VENV_TINYML ;;
    rag) env_key=GRAPHYN_WAVE1_VENV_RAG ;;
  esac
  echo "export ${env_key}=${venv_dir}"
}

for cap in "${CAPS[@]}"; do
  create_capability "$cap"
done

ENV_FILE="$ROOT/wave1_env.sh"
{
  echo "# Generated by install_wave1_plugin_venvs.sh — source me"
  echo "export GRAPHYN_WAVE1_VENVS_ROOT=\"$ROOT\""
  echo "export GRAPHYN_WAVE1_VENV_VISION=\"$ROOT/wave1-vision\""
  echo "export GRAPHYN_WAVE1_VENV_TINYML=\"$ROOT/wave1-tinyml\""
  echo "export GRAPHYN_WAVE1_VENV_RAG=\"$ROOT/wave1-rag\""
  echo "export GRAPHYN_WAVE1_FORCE_CPU=\"${GRAPHYN_WAVE1_FORCE_CPU:-1}\""
  echo "# Optional: let isolated boot install torch/ultralytics/chromadb"
  echo "# export GRAPHYN_ISOLATED_INSTALL_TORCH=1"
  echo "# export GRAPHYN_ISOLATED_INSTALL_ALL_OPTIONAL=1"
} > "$ENV_FILE"
log "wrote $ENV_FILE"
log "done. Source: source $ENV_FILE"
