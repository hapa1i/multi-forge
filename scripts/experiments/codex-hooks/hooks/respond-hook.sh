#!/usr/bin/env bash
# respond-hook.sh <event-label> <response-template> -- tee the payload (same
# capture as tee-hook.sh), then emit the canned response template.
#
# Template-name conventions:
#   *-exit2.*   -> print template to STDERR and exit 2 (the exit-code contract)
#   *-once.*    -> emit the template only the FIRST time this (label, template)
#                  pair fires; later firings exit 0 silently (bounds Stop-block loops)
#   otherwise   -> print template to STDOUT and exit 0 (the JSON-response contract)
set -u
LABEL="${1:?event label}"
TEMPLATE="${2:?response template path}"
DIR="${PROBE_CAPTURE_DIR:?}/payloads"
mkdir -p "$DIR"
TS="$(date +%s)$$"

cat >"$DIR/$LABEL-$TS.stdin.json"
pwd >"$DIR/$LABEL-$TS.pwd"

base="$(basename "$TEMPLATE")"
case "$base" in
*-once.*)
    GUARD="${PROBE_CAPTURE_DIR:?}/guards/$LABEL-$base.fired"
    if [ -e "$GUARD" ]; then
        exit 0
    fi
    : >"$GUARD"
    cat "$TEMPLATE"
    exit 0
    ;;
*-exit2.*)
    cat "$TEMPLATE" >&2
    exit 2
    ;;
*)
    cat "$TEMPLATE"
    exit 0
    ;;
esac
