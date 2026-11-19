#!/usr/bin/env bash
# Sandbox entrypoint: boot the Android emulator in a window on a virtual screen, served by noVNC on :6080.
# Creates /run/android-ready once Android has finished booting. /run is kept in memory, so a
# filesystem snapshot of a running phone does not carry the marker into the next Sandbox.
set -euo pipefail
test -c /dev/kvm || { echo "/dev/kvm is missing: Android needs the VM runtime with nested virtualization"; exit 1; }

export DISPLAY=:0
# A filesystem snapshot of a running phone carries lock files over, and the emulator refuses to start
# while the ones in its AVD folder exist.
rm -f /tmp/.X0-lock /tmp/.X11-unix/X0 "$ANDROID_AVD_HOME"/phone.avd/*.lock
Xvfb :0 -screen 0 1280x800x24 -ac -nolisten tcp >/tmp/xvfb.log 2>&1 &
until [ -S /tmp/.X11-unix/X0 ]; do sleep 0.1; done
x11vnc -display :0 -forever -shared -nopw -localhost -rfbport 5900 >/tmp/x11vnc.log 2>&1 &
websockify --web /usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &

# The emulator reaches its modem over the IPv6 loopback address, which only resolves while IPv6 is enabled.
# Without this the phone has no SIM and no cellular service, so no text messages or calls.
sysctl -qw net.ipv6.conf.all.disable_ipv6=0

# -scale shrinks the emulator window to fit the virtual screen; the phone itself keeps its resolution.
# EMULATOR_FLAGS adds flags of your own, such as "-grpc 8554" for tools that talk to the emulator directly.
emulator -avd phone -no-audio -no-boot-anim -no-snapshot -gpu swiftshader_indirect \
  -accel on -memory 4096 -scale 0.28 ${EMULATOR_FLAGS:-} >/tmp/emulator.log 2>&1 &
EMULATOR=$!

until [ "$(timeout 5 adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = 1 ]; do
  kill -0 "$EMULATOR" || { echo "The emulator exited before Android booted"; tail -40 /tmp/emulator.log; exit 1; }
  sleep 1
done

# Animations slow an agent down and make screenshots land mid-transition.
for scale in window_animation_scale transition_animation_scale animator_duration_scale; do
  adb shell settings put global "$scale" 0
done
adb shell input keyevent KEYCODE_MENU  # dismiss the lock screen
# The emulator shows a warning dialog about nested virtualization over its window; close it.
timeout 5 xdotool search --name "Nested Virtualization" windowfocus key Return 2>/dev/null || true

touch /run/android-ready
wait "$EMULATOR"
