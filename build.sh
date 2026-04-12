#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$ROOT_DIR/src-tauri/target/release"
APP_BUNDLE="$ROOT_DIR/src-tauri/target/release/bundle/macos/Local Voice Desktop.app"
BUNDLED_RUNTIME_DIR="$ROOT_DIR/.bundle-venv"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd npx
require_cmd cargo

prepare_bundled_python_runtime() {
  local source_venv_dir="$ROOT_DIR/.venv"
  local python_bin="$source_venv_dir/bin/python"
  local source_python
  local source_python_dir
  local source_python_name
  local source_lib_dir
  local source_libpython

  if [[ ! -x "$python_bin" ]]; then
    echo "Missing source Python runtime at $python_bin. Run 'uv sync' before building." >&2
    exit 1
  fi

  source_python="$($python_bin -c 'import pathlib, sys; print(pathlib.Path(sys.executable).resolve())')"
  if [[ ! -x "$source_python" ]]; then
    echo "Could not resolve the source interpreter behind $python_bin." >&2
    exit 1
  fi

  source_python_dir="$(dirname "$source_python")"
  source_python_name="$(basename "$source_python")"
  source_lib_dir="$(cd "$source_python_dir/../lib" && pwd)"
  source_libpython=("$source_lib_dir"/libpython*.dylib)
  if [[ ! -f "${source_libpython[0]}" ]]; then
    echo "Could not find libpython next to $source_python. Expected libpython*.dylib in $source_lib_dir." >&2
    exit 1
  fi

  echo "Preparing bundled Python runtime..."
  rm -rf "$BUNDLED_RUNTIME_DIR"
  cp -R "$source_venv_dir" "$BUNDLED_RUNTIME_DIR"

  rm -f \
    "$BUNDLED_RUNTIME_DIR/bin/python" \
    "$BUNDLED_RUNTIME_DIR/bin/python3" \
    "$BUNDLED_RUNTIME_DIR/bin/$source_python_name"

  cp "$source_python" "$BUNDLED_RUNTIME_DIR/bin/$source_python_name"
  ln -s "$source_python_name" "$BUNDLED_RUNTIME_DIR/bin/python"
  ln -s python "$BUNDLED_RUNTIME_DIR/bin/python3"

  mkdir -p "$BUNDLED_RUNTIME_DIR/lib"
  cp "${source_libpython[0]}" "$BUNDLED_RUNTIME_DIR/lib/"
  touch "$BUNDLED_RUNTIME_DIR/.gitkeep"
}

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg is not installed. Audio export/playback may fail at runtime." >&2
fi

prepare_bundled_python_runtime

cd "$ROOT_DIR"

echo "Cleaning previous release output..."
rm -rf "$RELEASE_DIR"

build_args=("$@")
has_bundles_arg=0
for arg in "${build_args[@]}"; do
  case "$arg" in
    --bundles|-b|--bundles=*|-b=*)
      has_bundles_arg=1
      break
      ;;
  esac
done

if [[ $has_bundles_arg -eq 0 ]]; then
  build_args=(--bundles app "${build_args[@]}")
fi

echo "Building Local Voice Desktop..."
npx @tauri-apps/cli build "${build_args[@]}"

echo
if [[ -d "$APP_BUNDLE" ]]; then
  echo "Build complete:"
  echo "  $APP_BUNDLE"
else
  echo "Build finished, but the macOS app bundle was not found at:"
  echo "  $APP_BUNDLE"
fi
