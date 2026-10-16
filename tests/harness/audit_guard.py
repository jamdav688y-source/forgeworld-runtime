"""TEST-ONLY fail-closed audit guard for ForgeWorld listener tests
(MISSION: FW-PHASE-1B-TCP-LOOPBACK-001).

Installed in the test runner and in every child Python process through
tests/harness/sitecustomize.py (an inherited PYTHONPATH entry). If it cannot
be installed, sitecustomize terminates the process with exit code 97 before
any test code runs.

Configuration (environment, all required unless noted):
  FW_GUARD_LOG            JSONL audit log (append)
  FW_GUARD_WRITE_ROOTS    ':'-separated directories writes are allowed under
  FW_GUARD_NET            "none" | "unix" | "tcp_loopback"
  FW_GUARD_SOCKET_ROOT    unix mode: AF_UNIX paths must live under this
  FW_GUARD_ENDPOINT_REGISTRY  tcp_loopback mode: endpoint lifecycle JSONL
  FW_GUARD_DENY_PORTS     optional ':'-separated 127.0.0.1 ports never connectable
  FW_GUARD_APPROVED_SCRIPTS   optional ':'-separated scripts children may run

Network policy in tcp_loopback mode:
  - AF_INET only (no AF_INET6, no AF_UNIX); bind only ("127.0.0.1", 0).
  - Every bind/listen/close of a guarded socket is recorded in the endpoint
    registry with the creating pid: registered -> listening -> closed.
  - connect only to ("127.0.0.1", port) when port is not denied, its latest
    registry state is "listening", its creating process is alive, and the
    kernel (/proc/net/tcp) shows a LISTEN socket on 127.0.0.1:port.
    Anything else -- stale, closed, unregistered, a dead creator -- is blocked.
  - name resolution only for the literal "127.0.0.1"; sendto blocked.
Every process logs one guard_installed record; every block is logged and
raises PermissionError.
"""
import json
import os
import socket
import sys

NET_MODES = ("none", "unix", "tcp_loopback")
TCP_LISTEN_STATE = "0A"


class GuardConfigurationError(Exception):
    pass


def _required(name):
    value = os.environ.get(name)
    if not value:
        raise GuardConfigurationError(f"missing required guard setting {name}")
    return value


class _Guard:
    def __init__(self):
        self.log_fd = os.open(_required("FW_GUARD_LOG"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        self.write_roots = [os.path.realpath(p) for p in _required("FW_GUARD_WRITE_ROOTS").split(":") if p]
        self.write_roots.append("/dev/null")
        self.net = _required("FW_GUARD_NET")
        if self.net not in NET_MODES:
            raise GuardConfigurationError(f"unknown FW_GUARD_NET {self.net!r}")
        self.socket_root = os.path.realpath(_required("FW_GUARD_SOCKET_ROOT")) if self.net == "unix" else None
        self.registry_fd = None
        self.registry_path = None
        if self.net == "tcp_loopback":
            self.registry_path = _required("FW_GUARD_ENDPOINT_REGISTRY")
            self.registry_fd = os.open(self.registry_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        self.deny_ports = {int(p) for p in os.environ.get("FW_GUARD_DENY_PORTS", "").split(":") if p}
        self.approved = {os.path.realpath(p) for p in os.environ.get("FW_GUARD_APPROVED_SCRIPTS", "").split(":") if p}
        self.pending_spawn = None
        self.endpoint_ports = {}  # id(socket) -> port, for sockets this process registered
        self.in_hook = False

    # -- records ----------------------------------------------------------
    def log(self, record):
        record.setdefault("pid", os.getpid())
        os.write(self.log_fd, (json.dumps(record) + "\n").encode())

    def endpoint_event(self, event, port):
        os.write(self.registry_fd, (json.dumps({"event": event, "port": port, "pid": os.getpid()}) + "\n").encode())

    def endpoint_state(self, port):
        latest = None
        with open(self.registry_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("port") == port:
                    latest = rec
        return latest

    @staticmethod
    def kernel_listening(port):
        try:
            with open("/proc/net/tcp", "r", encoding="ascii") as f:
                next(f)
                for line in f:
                    fields = line.split()
                    local, state = fields[1], fields[3]
                    ip_hex, port_hex = local.split(":")
                    if int(port_hex, 16) == port and ip_hex == "0100007F" and state == TCP_LISTEN_STATE:
                        return True
        except OSError:
            return False
        return False

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # -- path helpers -------------------------------------------------------
    @staticmethod
    def _under(path, roots):
        try:
            p = os.path.realpath(os.fsdecode(path))
        except Exception:
            return False
        return any(p == r or p.startswith(r + os.sep) for r in roots)

    @staticmethod
    def _resolve(path, args):
        path = os.fsdecode(path)
        if not os.path.isabs(path):
            fds = [a for a in args if isinstance(a, int) and not isinstance(a, bool) and a >= 0]
            if fds:
                try:
                    return os.path.join(os.readlink(f"/proc/self/fd/{fds[0]}"), path)
                except OSError:
                    pass
        return path

    # -- policy ---------------------------------------------------------------
    def decide(self, event, args):
        if event == "socket.__new__":
            family = args[1] if len(args) > 1 else None
            allowed = {"none": (), "unix": (socket.AF_UNIX,), "tcp_loopback": (socket.AF_INET,)}[self.net]
            if family not in allowed:
                return f"socket family {family} not allowed in {self.net} mode"
            return None
        if event == "socket.bind":
            addr = args[1] if len(args) > 1 else None
            if self.net == "unix":
                if not isinstance(addr, (str, bytes)) or addr[:1] in ("\0", b"\0") or not self._under(addr, [self.socket_root]):
                    return f"socket.bind {addr!r} outside socket root"
                return None
            if self.net == "tcp_loopback":
                if addr != ("127.0.0.1", 0):
                    return f"socket.bind {addr!r} (only ('127.0.0.1', 0) allowed)"
                return None
            return f"socket.bind {addr!r} blocked"
        if event == "socket.connect":
            addr = args[1] if len(args) > 1 else None
            if self.net == "unix":
                if not isinstance(addr, (str, bytes)) or addr[:1] in ("\0", b"\0") or not self._under(addr, [self.socket_root]):
                    return f"socket.connect {addr!r} outside socket root"
                return None
            if self.net == "tcp_loopback":
                if not (isinstance(addr, tuple) and len(addr) == 2 and addr[0] == "127.0.0.1" and isinstance(addr[1], int)):
                    return f"socket.connect {addr!r} (only 127.0.0.1 endpoints)"
                port = addr[1]
                if port in self.deny_ports:
                    return f"socket.connect 127.0.0.1:{port} denied port"
                state = self.endpoint_state(port)
                if state is None:
                    return f"socket.connect 127.0.0.1:{port} unregistered endpoint"
                if state["event"] != "listening":
                    return f"socket.connect 127.0.0.1:{port} endpoint is {state['event']} (stale)"
                if not self.alive(state["pid"]):
                    return f"socket.connect 127.0.0.1:{port} creator pid {state['pid']} is gone (stale)"
                if not self.kernel_listening(port):
                    return f"socket.connect 127.0.0.1:{port} not listening in the kernel (stale)"
                self.log({"allowed": "socket.connect", "port": port, "creator": state["pid"]})
                return None
            return f"socket.connect {addr!r} blocked"
        if event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex", "socket.gethostbyaddr"):
            host = args[0] if args else None
            if self.net == "tcp_loopback" and event == "socket.getaddrinfo" and host in ("127.0.0.1", b"127.0.0.1"):
                return None
            return f"{event} {host!r} blocked"
        if event in ("socket.sendto", "socket.sendmsg"):
            return f"{event} blocked"
        if event == "subprocess.Popen":
            argv = list(args[1]) if len(args) > 1 and args[1] is not None else []
            if len(argv) >= 2 and os.path.realpath(str(argv[0])) == os.path.realpath(sys.executable) \
                    and os.path.realpath(str(argv[1])) in self.approved:
                self.pending_spawn = [str(a) for a in argv]
                self.log({"allowed": "subprocess.Popen", "script": os.path.realpath(str(argv[1]))})
                return None
            return f"subprocess.Popen {argv[:2]!r} not approved"
        if event == "os.posix_spawn":
            argv = [str(a) for a in (args[1] if len(args) > 1 and args[1] is not None else [])]
            approved, self.pending_spawn = self.pending_spawn, None
            if approved is not None and argv == approved:
                return None
            return f"os.posix_spawn {argv[:2]!r} without a matching approved Popen"
        if event.startswith(("os.exec", "os.spawn", "os.fork")) or event in ("os.system", "pty.spawn"):
            return f"{event} blocked"
        if event == "open" and len(args) >= 2 and isinstance(args[0], (str, bytes, os.PathLike)):
            mode, flags = args[1], (args[2] if len(args) > 2 else 0)
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                      (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and not self._under(args[0], self.write_roots):
                return f"open-write {args[0]}"
            return None
        if event in ("os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.chmod", "os.symlink",
                     "os.link", "os.truncate", "shutil.rmtree", "shutil.copyfile", "shutil.move"):
            paths = [a for a in args if isinstance(a, (str, bytes, os.PathLike))]
            if event in ("shutil.copyfile", "os.symlink", "os.link"):
                paths = paths[1:2]  # only the destination is written; the source is read
            bad = [p for p in (self._resolve(a, args) for a in paths) if not self._under(p, self.write_roots)]
            if bad:
                return f"{event} {bad}"
        return None

    def hook(self, event, args):
        if self.in_hook:
            return
        self.in_hook = True
        try:
            reason = self.decide(event, args)
            if reason:
                self.log({"blocked": reason, "suite": os.environ.get("GUARD_SUITE")})
        finally:
            self.in_hook = False
        if reason:
            raise PermissionError(f"FW AUDIT GUARD BLOCKED: {reason}")

    # -- endpoint lifecycle tracking (tcp_loopback) ---------------------------
    def install_endpoint_tracking(self):
        guard = self
        original_bind, original_listen, original_close = socket.socket.bind, socket.socket.listen, socket.socket.close

        def bind(sock, address):
            original_bind(sock, address)
            if sock.family == socket.AF_INET:
                port = sock.getsockname()[1]
                guard.endpoint_ports[id(sock)] = port
                guard.endpoint_event("registered", port)

        def listen(sock, *args):
            original_listen(sock, *args)
            port = guard.endpoint_ports.get(id(sock))
            if port is not None:
                guard.endpoint_event("listening", port)

        def close(sock):
            port = guard.endpoint_ports.pop(id(sock), None)
            try:
                original_close(sock)
            finally:
                if port is not None:
                    guard.endpoint_event("closed", port)

        socket.socket.bind, socket.socket.listen, socket.socket.close = bind, listen, close


_GUARD = None


def install(role):
    """Install the guard in this process. Raises (-> exit 97 via
    sitecustomize) on any configuration problem."""
    global _GUARD
    guard = _Guard()
    if guard.net == "tcp_loopback":
        guard.install_endpoint_tracking()
    guard.log({"guard_installed": role, "net": guard.net, "ppid": os.getppid(),
               "argv0": os.path.realpath(sys.argv[0]) if sys.argv and sys.argv[0] else ""})
    sys.addaudithook(guard.hook)
    _GUARD = guard
    return guard
