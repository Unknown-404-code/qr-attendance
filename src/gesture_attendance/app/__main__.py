"""Run the attendance server.

    python -m gesture_attendance.app                       # LAN only (http://<laptop-ip>:8000)
    python -m gesture_attendance.app --tunnel --open       # + free public HTTPS link, opens the dashboard
"""
from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser

from ..config import load_config, parse_overrides


def lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def port_in_use(port: int) -> bool:
    """True if anything answers on localhost:port, or the port cannot be bound.
    (On Windows another app on 127.0.0.1:8000 can coexist with our 0.0.0.0:8000 and steal localhost traffic,
    so a bind test alone is not enough.)"""
    for host in ("127.0.0.1", "::1"):
        fam = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(fam, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", port))
    except OSError:
        return True
    return False


def free_port(start: int) -> int:
    for p in range(start, start + 50):
        if not port_in_use(p):
            return p
    raise SystemExit(f"no free port between {start} and {start + 49}")


def main(argv: list[str] | None = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--config", default=None)
    ap.add_argument("--set", nargs="*", default=[], help="config overrides, e.g. pipeline.mode=full app.base_url=https://x")
    ap.add_argument("--preload", action="store_true", help="load the models at startup instead of on first check-in")
    ap.add_argument("--tunnel", action="store_true", help="public HTTPS link via a Cloudflare quick tunnel")
    ap.add_argument("--open", action="store_true", help="open the sign-in page in the browser")
    ap.add_argument("--hosted", action="store_true",
                    help="run as the public server (Hugging Face): needs DATABASE_URL and GA_SECRET, no tunnel/LAN URL")
    args = ap.parse_args(argv)

    if args.hosted:
        import os
        missing = [k for k in ("DATABASE_URL", "GA_SECRET") if not os.environ.get(k)]
        if missing:
            raise SystemExit("Hosted mode needs these secrets: " + ", ".join(missing) + ". See DEPLOY.md.")

    import uvicorn

    from .main import create_app

    cfg = load_config(args.config, parse_overrides(args.set))

    port = args.port if args.hosted else free_port(args.port)
    if port != args.port:
        print(f"[!] Port {args.port} is already used by another program on this computer -> using port {port}.")
    args.port = port

    public = None
    if args.hosted:
        import os
        cfg["app"]["base_url"] = os.environ.get("GA_BASE_URL") or cfg["app"].get("base_url")  # None = from request
    elif args.tunnel and not cfg["app"].get("base_url"):
        print("[tunnel] starting Cloudflare quick tunnel ...")
        from .tunnel import start_tunnel
        public = start_tunnel(args.port)
        if public:
            cfg["app"]["base_url"] = public
        else:
            print("[tunnel] continuing without HTTPS: phones must be on the same Wi-Fi as this laptop")

    # the QR must contain an address phones can reach, never "localhost"
    if not cfg["app"].get("base_url") and not args.hosted:
        cfg["app"]["base_url"] = f"http://{lan_ip()}:{args.port}"
    app = create_app(cfg)
    if args.preload:
        import numpy as np

        from ..verify import build_verifier
        print("Loading models (first run downloads ~20 MB) ...")
        app.state.verifier = build_verifier(cfg)
        app.state.verifier.verify(np.zeros((480, 640, 3), np.uint8), cfg["gestures"][0], None)  # warm-up

    local = f"http://127.0.0.1:{args.port}"
    phones = cfg["app"]["base_url"] or "(the address phones open, taken from each request)"
    print("\n" + "=" * 72)
    print(f"  Sign in              : {local}/login")
    if app.state.generated_admin_password:
        print(f"  First admin account  : admin@localhost / {app.state.generated_admin_password}")
    print(f"  Phones will open     : {phones}   (encoded in the QR code)")
    print(f"  Gestures             : {', '.join(cfg['gestures'])}  [{cfg['models'].get('gesture_backend', 'mediapipe')}]")
    if not args.hosted and not phones.startswith("https"):
        print("  NOTE: without HTTPS phones use their camera app instead of a live preview (still works).")
    print("  Keep this window open during class. Ctrl+C to stop.")
    print("=" * 72 + "\n")
    if args.open and not args.hosted:
        threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"{local}/login")), daemon=True).start()
    if args.hosted:  # behind Hugging Face's HTTPS proxy: trust X-Forwarded-Proto so URLs and cookies use https
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", proxy_headers=True, forwarded_allow_ips="*")
    else:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
