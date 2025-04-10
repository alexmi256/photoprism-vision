#!/usr/bin/env bash

# https://docs.docker.com/develop/develop-images/build_enhancements/#to-enable-buildkit-builds
export DOCKER_BUILDKIT=1

if [[ -z $1 ]] || [[ -z $2 ]]; then
    echo "Usage: ${0##*/} [name] [linux/amd64|linux/arm64|linux/arm] [tag]" 1>&2
    exit 1
fi

NUMERIC='^[0-9]+$'
BUILD_DATE=$(/bin/date -u +%y%m%d)

# Remove existing vision-multibuilder.
echo "Removing old vision-multibuilder..."
docker buildx rm vision-multibuilder 2>/dev/null
sleep 3
echo "Done."

# Create new vision-multibuilder and add remote host for native arm builds.
echo "Creating new vision-multibuilder..."
docker buildx create --name vision-multibuilder --use 1>/dev/null || { echo 'buildx: failed to create vision-multibuilder'; exit 1; }
docker buildx create --name vision-multibuilder --append ssh://arm 2>/dev/null || echo 'buildx: failed to add remote host for native arm builds'
echo "Done."

echo "Starting 'photoprism/vision' multi-arch build based on $1/Dockerfile..."
echo "Build Arch: $2"

if [[ $1 ]] && [[ $2 ]] && [[ -z $3 ]]; then
    echo "Build Tags: preview"

    docker buildx build \
      --platform $2 \
      --pull \
      --no-cache \
      --build-arg BUILD_TAG=$BUILD_DATE \
      -f $1/Dockerfile \
      -t photoprism/vision:preview \
      --push $1
elif [[ $3 =~ $NUMERIC ]]; then
    echo "Build Tags: $3, latest"

    if [[ $4 ]]; then
      echo "Build Params: $4"
    fi

    docker buildx build \
      --platform $2 \
      --pull \
      --no-cache \
      --build-arg BUILD_TAG=$3 \
      -f $1/Dockerfile \
      -t photoprism/vision:latest \
      -t photoprism/vision:$3 $4 \
      --push $1
else
    echo "Build Tags: $3"

    if [[ $4 ]]; then
      echo "Build Params: $4"
    fi

    docker buildx build \
      --platform $2 \
      --pull \
      --no-cache \
      --build-arg BUILD_TAG=$BUILD_DATE \
      -f $1/Dockerfile \
      -t photoprism/vision:$3 $4 \
      --push $1
fi

echo "Removing vision-multibuilder..."
docker buildx rm vision-multibuilder

echo "Done."
