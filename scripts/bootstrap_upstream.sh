#!/usr/bin/env bash
# Fetch the exact upstream revision into an ignored directory. Does not vendor files.
set -euo pipefail
PIN='13dea6bab662ab1c4bbf87017e912e519907c8bc'
DEST="${1:-vendor/certpassly-exam-pipeline}"
if [[ -e "$DEST" ]]; then
  echo "Refusing to overwrite an existing directory: $DEST" >&2
  exit 2
fi
mkdir -p "$(dirname "$DEST")"
git init -q "$DEST"
git -C "$DEST" remote add origin https://github.com/msaqlainhaneef1/certpassly-exam-pipeline.git
git -C "$DEST" fetch --depth 1 origin "$PIN"
git -C "$DEST" checkout --detach -q FETCH_HEAD
ACTUAL="$(git -C "$DEST" rev-parse HEAD)"
[[ "$ACTUAL" == "$PIN" ]] || { echo 'Unapproved upstream version' >&2; exit 3; }
echo "Pinned upstream installed in $DEST at $ACTUAL"
