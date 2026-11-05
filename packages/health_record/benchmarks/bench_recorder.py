"""量測 record_success 單次平均微秒數（不屬於 pytest／CI 判定）。

用法：python packages/health_record/benchmarks/bench_recorder.py
"""
import logging
import time
import timeit

from smart_health_record import NodeRecorder

N = 200_000
REPEAT = 5


def main() -> None:
    rec = NodeRecorder("bench", time.monotonic, logging.getLogger("bench"))
    best = min(timeit.repeat(rec.record_success, number=N, repeat=REPEAT))
    avg = timeit.timeit(rec.record_success, number=N)
    print(f"record_success 平均 {avg / N * 1e6:.3f} 微秒/次（最佳一輪 {best / N * 1e6:.3f}），N={N}")
    assert avg / N * 1e6 < 20, "超過 20 微秒目標"


if __name__ == "__main__":
    main()
