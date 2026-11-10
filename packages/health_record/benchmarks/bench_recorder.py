"""量測 record_success、record_skip 單次平均微秒數（不屬於 pytest／CI 判定）。

用法：python packages/health_record/benchmarks/bench_recorder.py
"""
import logging
import time
import timeit

from smart_health_record import NodeRecorder

N = 200_000
REPEAT = 5


def bench(name, fn) -> None:
    best = min(timeit.repeat(fn, number=N, repeat=REPEAT))
    avg = timeit.timeit(fn, number=N)
    print(f"{name} 平均 {avg / N * 1e6:.3f} 微秒/次（最佳一輪 {best / N * 1e6:.3f}），N={N}")
    assert avg / N * 1e6 < 20, f"{name} 超過 20 微秒目標"


def main() -> None:
    rec = NodeRecorder("bench", time.monotonic, logging.getLogger("bench"))
    bench("record_success", rec.record_success)
    bench("record_skip", rec.record_skip)


if __name__ == "__main__":
    main()
