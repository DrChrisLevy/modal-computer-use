#!/usr/bin/env bash
# Sandbox entrypoint: a 1280x800 XFCE desktop on a virtual screen, served to browsers by noVNC on :6080.
# The desktop session belongs to the unprivileged `agent` user.
# Any arguments are a command to run on the desktop once it is up, such as a browser.
set -euo pipefail
if [ "$(id -u)" = 0 ]; then exec runuser -u agent -- bash "$0" "$@"; fi

export HOME=/home/agent DISPLAY=:0 XDG_RUNTIME_DIR=/tmp/runtime-agent
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

# A Sandbox restored from a snapshot can carry a stale lock for display :0.
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
# -ac lets other users in the Sandbox (the commands Modal runs as root) reach the display.
Xvfb :0 -screen 0 1280x800x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
until [ -S /tmp/.X11-unix/X0 ]; do sleep 0.1; done

dbus-daemon --session --address="unix:path=$XDG_RUNTIME_DIR/bus" --fork
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
startxfce4 >/tmp/xfce.log 2>&1 &
sleep 2
xset s off -dpms  # never blank the screen

if [ $# -gt 0 ]; then "$@" >/tmp/app.log 2>&1 & fi

x11vnc -display :0 -forever -shared -nopw -localhost -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
exec websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1
