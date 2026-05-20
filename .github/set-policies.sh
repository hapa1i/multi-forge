#!/usr/bin/env bash
# Configure GitHub repository settings for multi-forge.
#
# This repo is configured for a solo admin maintainer:
# - keep main unprotected so direct pushes stay possible
# - keep squash-only PR merges for public contribution cleanup
# - keep issues enabled, but turn off projects/wiki/discussions until needed
# - restrict PyPI trusted publishing to v* tags, even if the workflow trigger
#   is widened later
# - protect release tags from mutation/deletion, require signatures, and leave
#   initial tag creation possible
#
# Set STRICT_RELEASE_TAGS=1, or pass --strict-release-tags, to add upstream's
# creation rule and block creation of v* tags through the ruleset too.

set -euo pipefail

REPO=""
DRY_RUN="${DRY_RUN:-0}"
STRICT_RELEASE_TAGS="${STRICT_RELEASE_TAGS:-0}"
GITHUB_API_VERSION="${GITHUB_API_VERSION:-2022-11-28}"

PYPI_ENVIRONMENT="${PYPI_ENVIRONMENT:-pypi}"
PYPI_TAG_PATTERN="${PYPI_TAG_PATTERN:-v*}"
RELEASE_RULESET_NAME="${RELEASE_RULESET_NAME:-Protect release tags}"
RELEASE_REF_PATTERN="${RELEASE_REF_PATTERN:-refs/tags/v*}"

usage() {
    cat <<EOF
Usage: .github/set-policies.sh [options] [owner/repo]

Options:
  --repo OWNER/REPO        Repository to configure. Defaults to origin remote.
  --dry-run                Print planned writes without calling GitHub.
  --strict-release-tags    Also block creation of v* tags, matching upstream.
  --help                   Show this help.

Environment:
  DRY_RUN=1                Same as --dry-run.
  STRICT_RELEASE_TAGS=1    Same as --strict-release-tags.
  ALLOW_NON_ADMIN=1        Attempt writes even if gh does not report admin access.

The gh token must have Administration: write access for repository settings,
rulesets, and environment deployment branch policies.
EOF
}

info() {
    printf '==> %s\n' "$1"
}

warn() {
    printf 'warning: %s\n' "$1" >&2
}

fatal() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fatal "missing required command: $1"
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --repo)
                [[ $# -ge 2 ]] || fatal "--repo requires OWNER/REPO"
                REPO="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --strict-release-tags)
                STRICT_RELEASE_TAGS=1
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            -*)
                fatal "unknown option: $1"
                ;;
            *)
                [[ -z "$REPO" ]] || fatal "repository specified more than once"
                REPO="$1"
                shift
                ;;
        esac
    done
}

derive_repo_from_origin() {
    local url
    url="$(git remote get-url origin 2>/dev/null || true)"

    case "$url" in
        git@github.com:*)
            url="${url#git@github.com:}"
            ;;
        ssh://git@github.com/*)
            url="${url#ssh://git@github.com/}"
            ;;
        https://github.com/*)
            url="${url#https://github.com/}"
            ;;
        *)
            return 1
            ;;
    esac

    url="${url%.git}"
    [[ "$url" == */* && "$url" != */*/* ]] || return 1
    printf '%s\n' "$url"
}

normalize_flags() {
    case "$DRY_RUN" in
        1|true|TRUE|yes|YES) DRY_RUN=1 ;;
        0|false|FALSE|no|NO) DRY_RUN=0 ;;
        *) fatal "DRY_RUN must be 0 or 1" ;;
    esac

    case "$STRICT_RELEASE_TAGS" in
        1|true|TRUE|yes|YES) STRICT_RELEASE_TAGS=1 ;;
        0|false|FALSE|no|NO) STRICT_RELEASE_TAGS=0 ;;
        *) fatal "STRICT_RELEASE_TAGS must be 0 or 1" ;;
    esac
}

validate_repo() {
    if [[ -z "$REPO" ]]; then
        REPO="$(derive_repo_from_origin)" || fatal "could not derive OWNER/REPO from origin; pass --repo OWNER/REPO"
    fi

    [[ "$REPO" == */* && "$REPO" != */*/* ]] || fatal "repository must be OWNER/REPO, got: $REPO"
}

verify_admin_access() {
    if [[ "$DRY_RUN" == 1 ]]; then
        return
    fi

    local can_admin
    can_admin="$(gh repo view "$REPO" --json viewerCanAdminister --jq '.viewerCanAdminister' 2>/dev/null || true)"
    if [[ "$can_admin" != "true" ]]; then
        warn "gh does not report admin access for $REPO"
        warn "run 'gh auth status' and make sure the token has repository Administration: write"
        [[ "${ALLOW_NON_ADMIN:-0}" == 1 ]] || fatal "refusing to continue without admin access; set ALLOW_NON_ADMIN=1 to try anyway"
    fi
}

github_api() {
    gh api \
        -H "Accept: application/vnd.github+json" \
        -H "X-GitHub-Api-Version: $GITHUB_API_VERSION" \
        "$@"
}

github_api_json() {
    local method="$1"
    local endpoint="$2"
    local body="$3"

    if [[ "$DRY_RUN" == 1 ]]; then
        printf '+ gh api -X %s %s --input %s\n' "$method" "$endpoint" "$body"
        sed 's/^/    /' "$body"
        return
    fi

    github_api -X "$method" "$endpoint" --input "$body" >/dev/null
}

write_repo_settings_json() {
    local path="$1"
    cat >"$path" <<'JSON'
{
  "allow_squash_merge": true,
  "allow_merge_commit": false,
  "allow_rebase_merge": false,
  "delete_branch_on_merge": true,
  "has_issues": true,
  "has_projects": false,
  "has_wiki": false,
  "has_discussions": false
}
JSON
}

configure_repo_settings() {
    local body="$CONFIGURE_TMPDIR/repo-settings.json"
    write_repo_settings_json "$body"

    info "Configuring repository settings for $REPO"
    github_api_json PATCH "repos/$REPO" "$body"
}

write_environment_json() {
    local path="$1"
    cat >"$path" <<'JSON'
{
  "deployment_branch_policy": {
    "protected_branches": false,
    "custom_branch_policies": true
  }
}
JSON
}

configure_pypi_environment() {
    local body="$CONFIGURE_TMPDIR/environment.json"
    write_environment_json "$body"

    info "Configuring $PYPI_ENVIRONMENT environment with custom deployment policies"
    github_api_json PUT "repos/$REPO/environments/$PYPI_ENVIRONMENT" "$body"
}

ensure_pypi_tag_policy() {
    local endpoint="repos/$REPO/environments/$PYPI_ENVIRONMENT/deployment-branch-policies"
    local policy_id=""

    if [[ "$DRY_RUN" == 0 ]]; then
        policy_id="$(github_api "$endpoint" --jq ".branch_policies[] | select(.name == \"$PYPI_TAG_PATTERN\" and .type == \"tag\") | .id" 2>/dev/null || true)"
    fi

    if [[ -n "$policy_id" ]]; then
        info "PyPI environment already allows tag pattern $PYPI_TAG_PATTERN"
        return
    fi

    local body="$CONFIGURE_TMPDIR/pypi-tag-policy.json"
    cat >"$body" <<JSON
{
  "name": "$PYPI_TAG_PATTERN",
  "type": "tag"
}
JSON

    info "Allowing $PYPI_ENVIRONMENT deployments from $PYPI_TAG_PATTERN tags"
    github_api_json POST "$endpoint" "$body"
}

write_release_ruleset_json() {
    local path="$1"

    {
        cat <<JSON
{
  "name": "$RELEASE_RULESET_NAME",
  "target": "tag",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["$RELEASE_REF_PATTERN"],
      "exclude": []
    }
  },
  "rules": [
JSON

        if [[ "$STRICT_RELEASE_TAGS" == 1 ]]; then
            printf '    {"type": "creation"},\n'
        fi

        cat <<'JSON'
    {"type": "update"},
    {"type": "deletion"},
    {"type": "required_signatures"}
  ]
}
JSON
    } >"$path"
}

configure_release_tag_ruleset() {
    local ruleset_id=""
    if [[ "$DRY_RUN" == 0 ]]; then
        ruleset_id="$(github_api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$RELEASE_RULESET_NAME\" and .target == \"tag\") | .id" 2>/dev/null || true)"
    fi

    local body="$CONFIGURE_TMPDIR/release-tag-ruleset.json"
    write_release_ruleset_json "$body"

    if [[ -n "$ruleset_id" ]]; then
        info "Updating release tag ruleset: $RELEASE_RULESET_NAME"
        github_api_json PUT "repos/$REPO/rulesets/$ruleset_id" "$body"
    else
        info "Creating release tag ruleset: $RELEASE_RULESET_NAME"
        github_api_json POST "repos/$REPO/rulesets" "$body"
    fi
}

main() {
    parse_args "$@"
    normalize_flags
    require_command gh
    require_command git
    validate_repo
    verify_admin_access

    CONFIGURE_TMPDIR="$(mktemp -d)"
    trap 'rm -rf "$CONFIGURE_TMPDIR"' EXIT

    configure_repo_settings
    configure_pypi_environment
    ensure_pypi_tag_policy
    configure_release_tag_ruleset

    info "GitHub configuration complete for $REPO"
}

main "$@"
