#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${CARGO_TARGET_DIR:-$ROOT_DIR/src-tauri/target}/release"
APP_NAME="Local Voice Desktop.app"
APP_BUNDLE="$RELEASE_DIR/bundle/macos/$APP_NAME"
DMG_DIR="$RELEASE_DIR/bundle/dmg"
DMG_STAGING_DIR="$DMG_DIR/.staging"
DMG_PATH="$DMG_DIR/Local Voice Desktop.dmg"
BUNDLED_RUNTIME_DIR="$ROOT_DIR/.bundle-venv"
BUILD_VENV_DIR="$ROOT_DIR/.bundle-build-venv"
build_args=()
requested_bundles=()
prepare_only=0

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

parse_bundle_values() {
  local bundles_value="$1"
  local bundle
  local parsed=()
  IFS=',' read -r -a parsed <<< "$bundles_value"
  for bundle in "${parsed[@]}"; do
    bundle="${bundle//[[:space:]]/}"
    if [[ -n "$bundle" ]]; then
      requested_bundles+=("$bundle")
    fi
  done
}

parse_build_args() {
  local arg

  while (($#)); do
    arg="$1"
    case "$arg" in
      --prepare-runtime-only)
        prepare_only=1
        ;;
      --bundles|-b)
        shift
        if (($# == 0)); then
          echo "Missing value for $arg" >&2
          exit 1
        fi
        parse_bundle_values "$1"
        ;;
      --bundles=*|-b=*)
        parse_bundle_values "${arg#*=}"
        ;;
      *)
        build_args+=("$arg")
        ;;
    esac
    shift
  done

  if [[ ${#requested_bundles[@]} -eq 0 ]]; then
    if [[ "$build_platform" == Linux ]]; then
      requested_bundles=("deb")
    else
      requested_bundles=("app")
    fi
  fi
}

bundle_list_for_tauri() {
  local bundle
  local bundle_csv
  bundle_csv=""

  want_dmg=0
  want_app=0

  for bundle in "${requested_bundles[@]}"; do
    case "$bundle" in
      app)
        want_app=1
        if [[ -n "$bundle_csv" ]]; then
          bundle_csv+=","
        fi
        bundle_csv+="$bundle"
        ;;
      dmg)
        want_dmg=1
        ;;
      *)
        if [[ -n "$bundle_csv" ]]; then
          bundle_csv+=","
        fi
        bundle_csv+="$bundle"
        ;;
    esac
  done

  if [[ $want_app -eq 0 ]]; then
    if [[ -n "$bundle_csv" ]]; then
      bundle_csv="app,$bundle_csv"
    else
      bundle_csv="app"
    fi
    want_app=1
  fi

  if [[ ${#build_args[@]} -gt 0 ]]; then
    build_args=(--bundles "$bundle_csv" "${build_args[@]}")
  else
    build_args=(--bundles "$bundle_csv")
  fi
}

sign_app_bundle() {
  local app_bundle="$1"

  echo "Removing macOS extended attributes from app bundle..."
  xattr -cr "$app_bundle"

  echo "Signing macOS app bundle..."
  codesign --force --deep --sign - --timestamp=none "$app_bundle"

  echo "Verifying macOS app bundle..."
  codesign --verify --deep --strict --verbose=2 "$app_bundle"
}

create_dmg_from_app() {
  local app_bundle="$1"

  require_cmd hdiutil
  require_cmd ditto

  mkdir -p "$DMG_DIR"
  rm -rf "$DMG_STAGING_DIR"
  rm -f "$DMG_PATH"
  mkdir -p "$DMG_STAGING_DIR"

  ditto "$app_bundle" "$DMG_STAGING_DIR/$APP_NAME"
  ln -s /Applications "$DMG_STAGING_DIR/Applications"

  echo "Creating DMG from signed app bundle..."
  hdiutil create \
    -volname "Local Voice Desktop" \
    -srcfolder "$DMG_STAGING_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH" >/dev/null

  rm -rf "$DMG_STAGING_DIR"
}

build_platform="$(uname -s)"
case "$build_platform" in
  Darwin)
    parse_build_args "$@"
    bundle_list_for_tauri
    require_cmd codesign
    require_cmd ditto
    require_cmd xattr
    ;;
  Linux)
    parse_build_args "$@"
    if [[ ${#requested_bundles[@]} -ne 1 || "${requested_bundles[0]}" != "deb" ]]; then
      echo "Linux builds support only --bundles deb (Arch packaging is handled in T12)." >&2
      exit 1
    fi
    require_cmd uv
    ;;
  *) echo "Unsupported build platform: $build_platform" >&2; exit 1 ;;
esac
if [[ $prepare_only -eq 1 && "$build_platform" != Linux ]]; then
  echo "--prepare-runtime-only is Linux-only." >&2
  exit 1
fi
if [[ $prepare_only -eq 0 ]]; then
  require_cmd npx
  require_cmd cargo
fi

prepare_macos_python_runtime() {
  local source_venv_dir="$ROOT_DIR/.venv"
  local python_bin="$source_venv_dir/bin/python"
  local source_python
  local source_python_dir
  local source_python_name
  local source_python_version
  local source_lib_dir
  local source_libpython
  local source_stdlib_dir
  local source_stdlib_zip

  if [[ ! -x "$python_bin" ]]; then
    echo "Missing source Python runtime at $python_bin. Run 'uv sync' before building." >&2
    exit 1
  fi

  source_python="$($python_bin -c 'import pathlib, sys; print(pathlib.Path(sys.executable).resolve())')"
  source_python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ ! -x "$source_python" ]]; then
    echo "Could not resolve the source interpreter behind $python_bin." >&2
    exit 1
  fi

  source_python_dir="$(dirname "$source_python")"
  source_python_name="$(basename "$source_python")"
  source_lib_dir="$(cd "$source_python_dir/../lib" && pwd)"
  source_libpython=("$source_lib_dir"/libpython*.dylib)
  source_stdlib_dir="$source_lib_dir/python$source_python_version"
  source_stdlib_zip="$source_lib_dir/python${source_python_version/./}.zip"
  if [[ ! -f "${source_libpython[0]}" ]]; then
    echo "Could not find libpython next to $source_python. Expected libpython*.dylib in $source_lib_dir." >&2
    exit 1
  fi
  if [[ ! -d "$source_stdlib_dir" ]]; then
    echo "Could not find the Python standard library in $source_stdlib_dir." >&2
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
  ditto "$source_stdlib_dir" "$BUNDLED_RUNTIME_DIR/lib/python$source_python_version"
  if [[ -f "$source_stdlib_zip" ]]; then
    cp "$source_stdlib_zip" "$BUNDLED_RUNTIME_DIR/lib/"
  fi
  touch "$BUNDLED_RUNTIME_DIR/.gitkeep"
}

prepare_linux_python_runtime() {
  local python_bin source_root staging
  if [[ "$(uv --version)" != "uv 0.9.26" ]]; then
    echo "Linux build requires uv 0.9.26 for the locked runtime." >&2
    exit 1
  fi
  python_bin="$(uv python find 3.12.12 --managed-python)"
  source_root="$("$python_bin" -c 'import sys; print(sys.base_prefix)')"
  if [[ ! -f "$source_root/lib/libpython3.12.so.1.0" ]]; then
    echo "Managed Python 3.12.12 is missing libpython: $source_root" >&2
    exit 1
  fi

  # Keep the dependency environment disposable. Never bundle absolute venv links,
  # pyvenv.cfg, or the build machine's interpreter location.
  UV_PROJECT_ENVIRONMENT="$BUILD_VENV_DIR" uv sync --locked --python "$python_bin" \
    --managed-python --no-install-project --no-install-package en-core-web-sm --link-mode copy
  staging="$ROOT_DIR/.bundle-venv.tmp"
  rm -rf "$staging"
  cp -a "$source_root" "$staging"
  find "$staging/bin" -mindepth 1 -maxdepth 1 \
    ! -name python ! -name python3 ! -name python3.12 -exec rm -rf {} +
  cp -a "$BUILD_VENV_DIR/lib/python3.12/site-packages/." "$staging/lib/python3.12/site-packages/"
  rm -f "$staging/lib/python3.12/site-packages/_virtualenv.pth" \
    "$staging/lib/python3.12/site-packages/_virtualenv.py" \
    "$staging/lib/python3.12/site-packages/distutils-precedence.pth"
  # A .pth with absolute references can escape the package at runtime.
  if find "$staging/lib/python3.12/site-packages" -name '*.pth' -type f -print0 |
      xargs -0 -r grep -lE '^(/|import )' | grep -q .; then
    echo "Bundled site-packages contains non-relocatable .pth entries." >&2
    rm -rf "$staging"
    exit 1
  fi
  rm -rf "$BUNDLED_RUNTIME_DIR"
  mv "$staging" "$BUNDLED_RUNTIME_DIR"

  # Run from a relocated, read-only copy with no developer PATH or venv.
  local probe
  probe="$(mktemp -d)"
  cp -a --reflink=auto "$BUNDLED_RUNTIME_DIR" "$probe/runtime"
  cp -a "$ROOT_DIR/service" "$probe/service"
  chmod -R a-w "$probe/runtime"
  if ! (cd "$probe" && env -i HOME="$probe" PATH=/usr/bin:/bin \
      PYTHONHOME="$probe/runtime" PYTHONPATH="$probe" PYTHONNOUSERSITE=1 \
      "$probe/runtime/bin/python" -c \
      'import service.app, torch, kokoro, piper; import ssl, sqlite3; assert torch.version.cuda is None; print("Relocated CPU Python runtime imports succeeded")'); then
    chmod -R u+w "$probe/runtime"
    rm -rf "$probe"
    echo "Relocated Linux runtime failed its import check." >&2
    exit 1
  fi
  chmod -R u+w "$probe/runtime"
  rm -rf "$probe"
}

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg is not installed. Audio export/playback may fail at runtime." >&2
fi

if [[ "$build_platform" == Linux ]]; then
  prepare_linux_python_runtime
else
  prepare_macos_python_runtime
fi
if [[ $prepare_only -eq 1 ]]; then
  exit 0
fi

cd "$ROOT_DIR"

echo "Cleaning previous release output..."
rm -rf "$RELEASE_DIR"

echo "Building Local Voice Desktop..."
if [[ "$build_platform" == Linux ]]; then
  npx --yes @tauri-apps/cli@2.10.1 build --bundles deb "${build_args[@]}"
  echo "Linux bundle output: $RELEASE_DIR/bundle/deb/"
  exit 0
fi
npx --yes @tauri-apps/cli@2.10.1 build "${build_args[@]}"

echo
if [[ -d "$APP_BUNDLE" ]]; then
  sign_app_bundle "$APP_BUNDLE"

  if [[ $want_dmg -eq 1 ]]; then
    create_dmg_from_app "$APP_BUNDLE"
  fi

  echo "Build complete:"
  echo "  $APP_BUNDLE"
  if [[ $want_dmg -eq 1 ]]; then
    echo "  $DMG_PATH"
  fi
else
  echo "Build finished, but the macOS app bundle was not found at:"
  echo "  $APP_BUNDLE"
  exit 1
fi
