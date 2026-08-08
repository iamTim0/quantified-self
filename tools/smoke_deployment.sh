#!/usr/bin/env bash
#
# Check that a deployment is actually working, from the outside.
#
# Usage:
#     bash tools/smoke_deployment.sh https://your-host
#     OWNER_EMAIL=you@example.com OWNER_PASSWORD='…' bash tools/smoke_deployment.sh https://your-host
#
# Without credentials it runs the unauthenticated checks only. With them it also
# signs in, reads tenant-scoped data, and asks the deployment what it thinks of
# its own configuration — which is the part that says whether the installation is
# set up correctly rather than merely responding.
#
# The host is an argument on purpose: a deployment hostname does not belong in
# this repository (AGENTS.md rule 14).
#
# Two results are expected against a plain-http URL and are not defects of the
# deployment:
#
#   * `cookies_not_secure`, because Secure cookies cannot travel over http at
#     all, so a deployment reachable only over http has to turn them off. The
#     configuration check is therefore only graded for https URLs.
#   * curl will not send a Secure cookie over http either, so signing in against
#     an http URL requires COOKIE_SECURE=false on the server.
#
set -uo pipefail

BASE="${1:-}"
if [ -z "$BASE" ]; then
  echo "usage: bash tools/smoke_deployment.sh https://your-host" >&2
  exit 2
fi
BASE="${BASE%/}"

# Graded only over https — see the note above.
case "$BASE" in
  https://*) GRADE_CONFIG=true ;;
  *)         GRADE_CONFIG=false ;;
esac

pass=0 fail=0

# No `curl -k`: a certificate that does not validate is a finding, not an
# inconvenience to work around.
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$@"; }

ok()   { printf '  ok    %-42s %s\n' "$1" "${2:-}"; pass=$((pass + 1)); }
bad()  { printf '  FAIL  %-42s %s\n' "$1" "${2:-}"; fail=$((fail + 1)); }
note() { printf '        %s\n' "$1"; }

check() {
  local label=$1 expected=$2 actual=$3 hint=${4:-}
  if [ "$actual" = "$expected" ]; then
    ok "$label" "$actual"
  else
    bad "$label" "got $actual, expected $expected"
    [ -n "$hint" ] && note "$hint"
  fi
}

echo "Checking $BASE"
echo
echo "--- reachable ---"
check "gateway health" 200 "$(code "$BASE/health")"
check "dashboard"      200 "$(code "$BASE/")"

# Follows redirects and inspects the body. Without Traefik and the docs
# container, /docs/ is answered by the dashboard — which would pass as a 200 and
# prove nothing.
if curl -sL --max-time 20 "$BASE/docs/" 2>/dev/null \
   | grep -qi 'mkdocs\|Quantified Self Dokumentation'; then
  ok "documentation" "served"
else
  bad "documentation" "not the docs site"
  note "needs Traefik and the docs container; a stack started without them"
  note "answers /docs/ with the dashboard instead"
fi

echo
echo "--- closed by default ---"
# Registration is off by default. A 200 here means the deployment is open to
# anyone who knows the address.
check "signup refused" 403 \
  "$(code -X POST "$BASE/api/v1/auth/signup" -H 'Content-Type: application/json' \
      -d '{"email":"smoke-probe@example.test","password":"a-long-enough-password","name":"Probe"}')" \
  "set ALLOW_REGISTRATION=false and create the first account with core.create_owner"

# No session, no data. The single most important assertion here.
check "metrics need a session" 401 "$(code "$BASE/api/v1/data/metrics")"

# Core serves decrypted connector credentials on /internal. It must not be
# reachable through the public edge at all.
internal=$(code "$BASE/api/v1/internal/data/sources/oura/token")
if [ "$internal" = "200" ]; then
  bad "internal API not exposed" "200 — decrypted credentials are publicly reachable"
else
  ok "internal API not exposed" "$internal"
fi

if [ -z "${OWNER_EMAIL:-}" ] || [ -z "${OWNER_PASSWORD:-}" ]; then
  echo
  echo "--- signed-in checks skipped ---"
  note "set OWNER_EMAIL and OWNER_PASSWORD to also check login, a tenant-scoped"
  note "read, and what the deployment reports about its own configuration"
else
  jar=$(mktemp)
  echo
  echo "--- signed in as $OWNER_EMAIL ---"
  check "login" 200 "$(curl -s -c "$jar" -o /dev/null -w '%{http_code}' --max-time 20 \
    -X POST "$BASE/api/v1/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\":\"$OWNER_EMAIL\",\"password\":\"$OWNER_PASSWORD\"}")" \
    "over http this also needs COOKIE_SECURE=false on the server"

  check "metrics with session" 200 \
    "$(curl -s -b "$jar" -o /dev/null -w '%{http_code}' --max-time 20 "$BASE/api/v1/data/metrics")"

  echo
  echo "--- what the deployment says about itself ---"
  body=$(curl -s -b "$jar" --max-time 20 "$BASE/api/v1/data/system/warnings")

  # Graded in the shell, not in Python. This check used to run `python`, which
  # Debian and Ubuntu do not alias, with the error going to /dev/null -- and the
  # resulting empty output was read as "nothing to report", so a deployment running
  # on published default secrets was graded clean. Reaching for python3 instead
  # only moved the problem: this script is shipped in the release bundle to hosts
  # that are documented as needing Docker and nothing else, and failing a healthy
  # deployment because the operator's machine has no interpreter is not better.
  #
  # The verdict therefore comes from the response itself, which needs no tools. An
  # empty `warnings` array is the one shape that means "clean"; anything else is
  # either a finding or an answer this script does not understand, and neither is a
  # pass.
  case "$body" in
    *'"warnings":[]'* | *'"warnings": []'*) config_state=clean ;;
    *'"severity"'*)                        config_state=problems ;;
    *)                                     config_state=unreadable ;;
  esac

  # Python only formats, when it happens to be there. Without it the raw body is
  # printed instead -- less pleasant to read, and it says the same thing.
  if [ "$config_state" = problems ]; then
    py=""
    for candidate in python3 python; do
      if command -v "$candidate" > /dev/null 2>&1; then
        py="$candidate"
        break
      fi
    done

    pretty=""
    if [ -n "$py" ]; then
      pretty=$(printf '%s' "$body" | "$py" -c "
import json, sys
for w in json.load(sys.stdin)['warnings']:
    print(f\"[{w['severity']}] {w['code']}: {w['title']}\")
    print(f\"    -> {w['action']}\")
" 2>/dev/null)
    fi

    if [ -n "$pretty" ]; then
      printf '%s\n' "$pretty" | sed 's/^/        /'
    else
      note "raw: $body"
    fi
  fi

  case "$config_state" in
    clean)
      ok "configuration" "nothing to report"
      ;;
    problems)
      if [ "$GRADE_CONFIG" = true ]; then
        bad "configuration" "the deployment is reporting problems"
      else
        ok "configuration" "reported above, not graded over http"
      fi
      ;;
    unreadable)
      note "raw: $body"
      bad "configuration" "could not read the deployment's own report"
      ;;
  esac
  rm -f "$jar"
fi

echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
