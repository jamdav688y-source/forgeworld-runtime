#!/usr/bin/env bash
# Lightweight, dependency-free schema validation: checks that every field
# listed in a schema's top-level "required" array is present and non-null
# in an instance document. Deliberately not a full JSON Schema validator
# (no `jsonschema` package is installed and we're not adding one, per
# "do not introduce unnecessary dependencies" / offline-first) - this
# covers the actual failure mode we care about, a mission or evidence
# package silently missing a required field.
#
# Usage: validate-schema.sh SCHEMA_FILE INSTANCE_FILE
# Exit 0 = required fields present, exit 1 = one or more missing.

set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$here/lib.sh"
require_jq

schema="${1:?schema file required}"
instance="${2:?instance file required}"

missing="$(jq -n --slurpfile schema "$schema" --slurpfile doc "$instance" \
  '($schema[0].required // []) as $req | $doc[0] as $d |
   [$req[] as $f | select(($d[$f] == null) or ($d[$f] == "")) | $f]')"

count=$(echo "$missing" | jq 'length')
if [ "$count" -eq 0 ]; then
  echo "PASS: $instance satisfies required fields in $schema"
  exit 0
else
  echo "FAIL: $instance is missing required fields: $(echo "$missing" | jq -c .)"
  exit 1
fi
