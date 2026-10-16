"""TEST-ONLY. Run as the first process inside `unshare --net` (a fresh
network namespace, which starts with only a DOWN loopback interface). Brings
`lo` up with an ioctl (no `ip` tool needed), verifies the namespace has no
interface other than lo and no routes, then execs the given command with
FW_GUARD=1. Runs BEFORE the guard is installed (FW_GUARD must be 0 here)."""
import fcntl
import os
import socket
import struct
import sys

SIOCGIFFLAGS, SIOCSIFFLAGS, IFF_UP = 0x8913, 0x8914, 0x1


def main():
    if os.environ.get("FW_GUARD") != "0":
        sys.stderr.write("netns_bootstrap must run with FW_GUARD=0\n")
        sys.exit(97)
    with open("/proc/net/dev", encoding="ascii") as f:
        interfaces = [line.split(":")[0].strip() for line in f.readlines()[2:]]
    if interfaces != ["lo"]:
        sys.stderr.write(f"refusing: network namespace has interfaces {interfaces}, expected only lo\n")
        sys.exit(97)
    with open("/proc/net/route", encoding="ascii") as f:
        routes = f.readlines()[1:]
    if routes:
        sys.stderr.write(f"refusing: network namespace has routes {routes}\n")
        sys.exit(97)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # ioctl handle only; never sends
    try:
        ifr = struct.pack("16sH14s", b"lo", 0, b"\0" * 14)
        flags = struct.unpack("16sH14s", fcntl.ioctl(s, SIOCGIFFLAGS, ifr))[1]
        fcntl.ioctl(s, SIOCSIFFLAGS, struct.pack("16sH14s", b"lo", flags | IFF_UP, b"\0" * 14))
    finally:
        s.close()
    env = dict(os.environ, FW_GUARD="1")
    os.execve(sys.executable, [sys.executable] + sys.argv[1:], env)


if __name__ == "__main__":
    main()
