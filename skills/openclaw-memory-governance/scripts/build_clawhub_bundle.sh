#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${1:-${SKILL_DIR}/dist}"
mkdir -p "${OUT_DIR}"

BUNDLE="${OUT_DIR}/openclaw-memory-governance.zip"
rm -f "${BUNDLE}"

(
  cd "${SKILL_DIR}"
  zip -r "${BUNDLE}" SKILL.md agents references scripts >/dev/null
)

echo "bundle_created=${BUNDLE}"
