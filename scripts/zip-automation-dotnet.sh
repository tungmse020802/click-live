#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT_DIR"

echo "Creating clean automation-dotnet.zip..."
rm -f automation-dotnet.zip

zip -r automation-dotnet.zip automation-dotnet -x "automation-dotnet/bin/*" "automation-dotnet/obj/*" "automation-dotnet/dist/*" "automation-dotnet/.vs/*" "automation-dotnet/*.user"

echo "Created automation-dotnet.zip successfully!"
