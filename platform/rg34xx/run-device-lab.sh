#!/bin/sh
# Device-local only. Does not launch an emulator, read saves, or bind the LAN.
set -eu
if [ "$#" -ne 2 ]; then
    echo "Usage: sh run-device-lab.sh /absolute/helix-source /absolute/lab-journal.sqlite" >&2
    exit 2
fi
case "$1:$2" in /*:/*) ;; *) echo "Both paths must be absolute." >&2; exit 2;; esac
helix_runtime_python=${HELIX_PYTHON:-python3}
"$helix_runtime_python" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
cd "$1"
exec "$helix_runtime_python" -m companion.lab_service --host 127.0.0.1 --port 8765 --journal "$2"
