"""命令列入口：python -m mock_service --profile {edge,api} ..."""
import argparse
import importlib
import logging
import signal
import sys
import threading

from .settings import Settings


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="mock_service", description="smart_health 模擬服務")
    p.add_argument("--profile", choices=["edge", "api"], required=True)
    p.add_argument("--instance", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--control-port", type=int, required=True)
    p.add_argument("--stale-after-s", type=float, default=5.0)
    p.add_argument("--stuck-after-s", type=float, default=3.0)
    p.add_argument("--startup-grace-s", type=float, default=30.0)
    p.add_argument("--error-window-s", type=float, default=30.0)
    p.add_argument("--tick-interval-s", type=float, default=1.0)
    args = p.parse_args(argv)
    if args.stuck_after_s >= args.stale_after_s:
        p.error("--stuck-after-s 必須小於 --stale-after-s")
    if args.port == args.control_port:
        p.error("--port 與 --control-port 不可相同")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # 延後 import：參數錯誤時不用載入函式庫
    from .control import ControlServer
    from .simulator import Simulator

    profile = importlib.import_module(f"mock_service.profiles.{args.profile}")
    settings = Settings(
        instance=args.instance, host=args.host, port=args.port,
        stale_after_s=args.stale_after_s, stuck_after_s=args.stuck_after_s,
        startup_grace_s=args.startup_grace_s, error_window_s=args.error_window_s,
        tick_interval_s=args.tick_interval_s)

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    simulator = Simulator(profile, settings)
    control = None
    try:
        simulator.start()
        control = ControlServer(simulator, args.host, args.control_port)
    except OSError as exc:
        simulator.stop()
        print(f"mock_service 無法綁定連接埠：{exc}（status port {args.port}、"
              f"control port {args.control_port}）", file=sys.stderr, flush=True)
        return 2
    control.start()
    print(f"mock_service ready profile={args.profile} instance={args.instance} "
          f"port={args.port} control_port={args.control_port}", flush=True)
    stop.wait()
    control.stop()
    simulator.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
