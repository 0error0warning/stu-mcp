#!/bin/sh
# A single personal server. No browser debugging port, public desktop, or
# unattended school login. Authentication is completed by the operator.
set -eu
umask 077

if [ "${1:-}" != "serve" ]; then
    exec stu-mcp "$@"
fi

children=""
stop_children() {
    trap '' INT TERM
    trap - EXIT
    for child in $children; do kill "$child" 2>/dev/null || true; done
    # Bound graceful shutdown. A stuck request or a child ignoring TERM must
    # not prevent the supervisor from exiting and the restart policy running.
    attempts=0
    while [ "$attempts" -lt 20 ]; do
        alive=0
        for child in $children; do
            if kill -0 "$child" 2>/dev/null; then alive=1; fi
        done
        [ "$alive" -ne 0 ] || break
        attempts=$((attempts + 1))
        sleep 0.1
    done
    for child in $children; do
        if kill -0 "$child" 2>/dev/null; then kill -KILL "$child" 2>/dev/null || true; fi
    done
    for child in $children; do wait "$child" 2>/dev/null || true; done
}
trap stop_children EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
start_child() {
    "$@" &
    children="$children $!"
}
fail() {
    echo "$1" >&2
    exit 1
}

case "${STU_MCP_INTERACTION:-disabled}" in
    disabled) ;;
    virtual-display)
        : "${STU_MCP_VNC_AUTH_FILE:?Set STU_MCP_VNC_AUTH_FILE to an x11vnc -storepasswd file}"
        [ -f "$STU_MCP_VNC_AUTH_FILE" ] && [ -r "$STU_MCP_VNC_AUTH_FILE" ] ||
            fail "Virtual display requires a readable VNC authentication file."
        export DISPLAY=:99
        export XAUTHORITY=/run/stu-mcp/Xauthority
        touch "$XAUTHORITY"
        python -c 'import secrets; print("add :99 MIT-MAGIC-COOKIE-1 " + secrets.token_hex(16))' |
            xauth -f "$XAUTHORITY" source -
        [ -s "$XAUTHORITY" ] || fail "X11 authentication initialization failed."
        start_child Xvfb "$DISPLAY" -screen 0 1440x1000x24 -nolisten tcp -auth "$XAUTHORITY"
        attempts=0
        until xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; do
            attempts=$((attempts + 1))
            [ "$attempts" -lt 30 ] || fail "Virtual display did not become available."
            sleep 0.1
        done
        start_child openbox --sm-disable
        start_child x11vnc -display "$DISPLAY" -auth "$XAUTHORITY" -forever -shared \
            -localhost -rfbport 5900 -rfbauth "$STU_MCP_VNC_AUTH_FILE" -quiet
        start_child websockify --web /usr/share/novnc 0.0.0.0:6080 127.0.0.1:5900
        ;;
    *) fail "Container interaction supports disabled or virtual-display; no desktop is bundled by default." ;;
esac

if [ "${STU_MCP_SETUP:-0}" = "1" ]; then
    # Keep the capability URL out of container logs. An operator reads this
    # private file with docker compose exec; it is not an MCP tool result.
    stu-mcp setup --port 8766 --no-browser > /run/stu-mcp/setup-url &
    children="$children $!"
    # Setup itself retains its loopback Host/Origin checks. Publish this bridge
    # as HOST 127.0.0.1:8766 -> CONTAINER 8876, preserving the browser's Host.
    start_child socat TCP-LISTEN:8876,bind=0.0.0.0,reuseaddr,fork TCP:127.0.0.1:8766
fi

stu-mcp "$@" &
main=$!
children="$children $main"
while kill -0 "$main" 2>/dev/null; do
    for child in $children; do
        kill -0 "$child" 2>/dev/null || fail "A required server component stopped; shutting down."
    done
    sleep 1
done
wait "$main"
