#!/usr/bin/env bash
set -euo pipefail

image=$1
repository=${image#ghcr.io/}
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT

token=$(curl --fail --silent --show-error --retry 2 --connect-timeout 20 --max-time 60 \
  "https://ghcr.io/token?service=ghcr.io&scope=repository:$repository:pull" | jq -er .token)

# A Git tag alone does not make a container release. Select the highest
# stable version with a public image, including historical unprefixed tags.
versions=$(git tag --list 'v*' --sort=-version:refname)
while IFS= read -r version; do
  [[ "$version" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || continue
  for tag in "$version" "${version#v}"; do
    status=$(curl --silent --show-error --retry 2 --connect-timeout 20 --max-time 60 \
      -H "Authorization: Bearer $token" \
      -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
      -o "$scratch/manifest.json" -D "$scratch/headers" -w '%{http_code}' \
      "https://ghcr.io/v2/$repository/manifests/$tag")
    case "$status" in
      404) continue ;;
      200) ;;
      *) printf 'Cannot verify %s:%s (HTTP %s).\n' "$image" "$tag" "$status" >&2; exit 1 ;;
    esac
    if [[ "$tag" == "$version" ]]; then
      jq -e '[.manifests[].platform | select(.os == "linux") | .architecture] |
        (index("amd64") != null and index("arm64") != null)' "$scratch/manifest.json" >/dev/null
    fi
    digest=$(tr -d '\r' < "$scratch/headers" | awk 'tolower($1) == "docker-content-digest:" {print $2}')
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]
    docker buildx imagetools create --prefer-index=false --tag "$image:latest" "$image@$digest"
    DOCKER_CONFIG=$(mktemp -d "$scratch/anonymous.XXXXXX") docker manifest inspect "$image:latest" >/dev/null
    printf '`%s:latest` points to `%s`.\n' "$image" "$tag"
    exit 0
  done
done <<< "$versions"

printf 'No public stable release exists for %s.\n' "$image" >&2
exit 1
