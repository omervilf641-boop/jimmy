"""
A stand-in for the orb, so the computer's half can be finished and tested
before the board has cleared customs.

It listens on the same UDP port the real thing will, and prints what arrives
along with how the ring is meant to look. When the ESP32 turns up, this is what
its firmware has to reproduce — and if the two disagree, the difference is
already written down here rather than being discovered by staring at an
unlit ring.

    python orb_stub.py
"""
import socket
import sys
import time

PORT = 8124

LOOKS_LIKE = {
    "idle":      "one dim dot, orbiting slowly",
    "listening": "full ring, one bright flash",
    "thinking":  "a short arc chasing round",
    "speaking":  "the whole ring breathing",
}

s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("0.0.0.0", PORT))
print(f"pretending to be the orb, listening on UDP {PORT}\nctrl-c to stop\n")

started = time.time()
seen = 0
while True:
    data, addr = s.recvfrom(64)
    state = data.decode("ascii", "replace").strip()
    seen += 1
    t = time.time() - started
    note = LOOKS_LIKE.get(state, "?? unknown state, the firmware should ignore it")
    print(f"[{t:6.1f}s] {state:<10} from {addr[0]:<15} -> {note}", flush=True)
