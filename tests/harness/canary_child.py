"""TEST-ONLY canary, run as a guarded CHILD by tests/harness/test_audit_guard.py.
Usage: canary_child.py <scenario> [args...]; prints one JSON result line."""
import json
import os
import socket
import subprocess
import sys


def attempt(fn):
    try:
        fn()
        return "ALLOWED"
    except PermissionError:
        return "BLOCKED"
    except Exception as exc:  # noqa: BLE001
        return f"OTHER:{type(exc).__name__}"


def tcp_scenario():
    r = {}
    r["af_inet6"] = attempt(lambda: socket.socket(socket.AF_INET6, socket.SOCK_STREAM))
    r["af_unix"] = attempt(lambda: socket.socket(socket.AF_UNIX, socket.SOCK_STREAM))
    r["dns_name"] = attempt(lambda: socket.getaddrinfo("example.com", 443))
    r["bind_nonzero_port"] = attempt(lambda: socket.socket().bind(("127.0.0.1", 18999)))
    r["bind_wildcard"] = attempt(lambda: socket.socket().bind(("0.0.0.0", 0)))
    r["connect_unregistered"] = attempt(lambda: socket.socket().connect(("127.0.0.1", 18998)))
    deny = int(os.environ.get("FW_GUARD_DENY_PORTS", "0").split(":")[0] or 0)
    r["connect_denied_port"] = attempt(lambda: socket.socket().connect(("127.0.0.1", deny)))
    # an endpoint whose recorded creator is gone must be stale
    with open(os.environ["FW_GUARD_ENDPOINT_REGISTRY"], "a") as f:
        f.write(json.dumps({"event": "listening", "port": 18997, "pid": 2 ** 22 + 1}) + "\n")
    r["connect_dead_creator"] = attempt(lambda: socket.socket().connect(("127.0.0.1", 18997)))
    # Each of the three connect checks, isolated so that removing any single
    # layer is detected: registry state, creator liveness, kernel LISTEN state.
    registry = os.environ["FW_GUARD_ENDPOINT_REGISTRY"]

    def live_listener():
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s, s.getsockname()[1]

    def append(event, port, pid):
        with open(registry, "a") as f:
            f.write(json.dumps({"event": event, "port": port, "pid": pid}) + "\n")

    listener, p_state = live_listener()          # kernel LISTEN, creator alive, record says closed
    append("closed", p_state, os.getpid())
    r["layer_state_closed_record"] = attempt(lambda: socket.socket().connect(("127.0.0.1", p_state)))
    listener2, p_creator = live_listener()       # kernel LISTEN, record listening, creator dead
    append("listening", p_creator, 2 ** 22 + 2)
    r["layer_creator_dead"] = attempt(lambda: socket.socket().connect(("127.0.0.1", p_creator)))
    append("listening", 18996, os.getpid())      # record listening, creator alive, nothing in the kernel
    r["layer_kernel_not_listening"] = attempt(lambda: socket.socket().connect(("127.0.0.1", 18996)))
    listener.close()
    listener2.close()
    # the approved path: own listener on an OS-assigned port, one round trip
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    client = socket.socket()
    r["connect_active_endpoint"] = attempt(lambda: client.connect(("127.0.0.1", port)))
    if r["connect_active_endpoint"] == "ALLOWED":
        peer, _ = server.accept()
        client.sendall(b"ping")
        r["round_trip"] = "OK" if peer.recv(4) == b"ping" else "BAD"
        peer.close()
    client.close()
    server.close()
    r["connect_after_close"] = attempt(lambda: socket.socket().connect(("127.0.0.1", port)))
    r["subprocess_unapproved"] = attempt(lambda: subprocess.run(["/bin/true"]))
    r["os_system"] = attempt(lambda: os.system("true"))
    r["write_outside"] = attempt(lambda: open(sys.argv[2], "w"))
    return r


def marker_scenario():
    # Reaching this line at all would be a failure for the fail-closed tests.
    with open(sys.argv[2], "w") as f:
        f.write("side effect")
    return {"wrote_marker": True}


if __name__ == "__main__":
    scenario = sys.argv[1]
    print(json.dumps({"tcp": tcp_scenario, "marker": marker_scenario}[scenario]()))
