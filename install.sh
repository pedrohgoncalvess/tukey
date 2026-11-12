#!/bin/sh
# Install Tukey for the current user on Linux or macOS.
set -eu

case "$(uname -s)" in
    Linux|Darwin) ;;
    *) echo "Use install.ps1 on Windows." >&2; exit 1 ;;
esac

if [ "$#" -gt 1 ]; then
    echo "Usage: sh install.sh [source-directory-or-archive-url]" >&2
    exit 2
fi
source=${1:-https://github.com/pedrohgoncalvess/tukey/archive/refs/heads/main.zip}

download() {
    if command -v curl >/dev/null 2>&1; then
        curl --fail --show-error --silent --location "$1" --output "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget --quiet --output-document="$2" "$1"
    else
        echo "Install curl or wget to download uv, then run this installer again." >&2
        return 1
    fi
}

if command -v uv >/dev/null 2>&1; then
    uv=$(command -v uv)
elif [ -x "${UV_INSTALL_DIR:-$HOME/.local/bin}/uv" ]; then
    uv=${UV_INSTALL_DIR:-$HOME/.local/bin}/uv
elif [ -x "$HOME/.cargo/bin/uv" ]; then
    uv=$HOME/.cargo/bin/uv
else
    echo "Installing uv from astral.sh..."
    installer=$(mktemp)
    trap 'rm -f "$installer"' 0
    download https://astral.sh/uv/install.sh "$installer"
    UV_INSTALL_DIR="${UV_INSTALL_DIR:-$HOME/.local/bin}" UV_NO_MODIFY_PATH=1 sh "$installer"
    uv=${UV_INSTALL_DIR:-$HOME/.local/bin}/uv
    if [ ! -x "$uv" ]; then
        echo "uv was not found at $uv after installation." >&2
        exit 1
    fi
fi

echo "Installing Tukey from $source..."
"$uv" tool install --reinstall --python 3.12 "$source"
bin_dir=$("$uv" tool dir --bin)
if ! "$uv" tool update-shell; then
    echo "Warning: could not update the shell configuration. Add $bin_dir to your PATH." >&2
fi
"$bin_dir/tukey" --version
printf '\nTukey is installed in %s.\n' "$bin_dir"
echo "Open a new terminal, then run: tukey --help"
