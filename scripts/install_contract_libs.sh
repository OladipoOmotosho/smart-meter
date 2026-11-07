#!/bin/sh
set -eu

if ! command -v forge >/dev/null 2>&1; then
    echo 'Foundry v1.9.0 is required; install it before make install.' >&2
    exit 1
fi

install_at_revision() {
    name=$1
    url=$2
    revision=$3
    destination="contracts/lib/$name"
    if [ ! -d "$destination/.git" ]; then
        if [ -e "$destination" ]; then
            echo "$destination exists but is not a Git checkout; inspect it manually." >&2
            exit 1
        fi
        git clone --filter=blob:none "$url" "$destination"
    fi
    git -C "$destination" fetch --depth 1 origin "$revision"
    git -C "$destination" checkout --detach "$revision"
    actual=$(git -C "$destination" rev-parse HEAD)
    if [ "$actual" != "$revision" ]; then
        echo "$name revision mismatch: $actual" >&2
        exit 1
    fi
    echo "$name: $actual"
}

install_at_revision openzeppelin-contracts \
    https://github.com/OpenZeppelin/openzeppelin-contracts.git \
    c64a1edb67b6e3f4a15cca8909c9482ad33a02b0
install_at_revision forge-std \
    https://github.com/foundry-rs/forge-std.git \
    bf647bd6046f2f7da30d0c2bf435e5c76a780c1b
