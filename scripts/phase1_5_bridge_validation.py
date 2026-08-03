"""Phase 1.5 Bridge Integration & Stability Validation harness.

Exercises the REAL titan_protocol.bridge server (ThreadingHTTPServer + real
sockets) end to end: sustained load, fault injection (network gaps,
slow clients, MT5/Terminal-outage proxy via heartbeat gaps, Python
process-restart proxy), stress/concurrency, security, and observability
capture. This is a validation tool, not production code.

Honesty notes:
- No real MT5/MetaEditor/broker exists in this sandbox. "MT5 restart"/
  "Terminal unavailable"/"Broker recovery" are tested as the BRIDGE's
  observable behavior when EA-side HTTP traffic stops and resumes --
  not a literal MT5.exe restart, which cannot be performed here.
- "Long duration" is a bounded, sustained run (duration recorded in the
  results), not a multi-day soak.
"""
from __future__ import annotations

import json
import logging
import resource
import socket
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from titan_protocol.bridge.command_queue import CommandQueue
from titan_protocol.bridge.config import BridgeConfig
from titan_protocol.bridge.connection_health import ConnectionHealth
from titan_protocol.bridge.engine import BridgeEngine
from titan_protocol.bridge.metrics import BridgeMetrics
from titan_protocol.bridge.models import CommandKind, SCHEMA_VERSION, TradeCommand
from titan_protocol.bridge.server import API_KEY_HEADER, serve

API_KEY = "phase1_5-secret"
MAGIC = 20260709
SYMBOL = "EURUSD"

results = {}
log_records = []


class _CapturingHandler(logging.Handler):
    def emit(self, record):
        log_records.append(record)


def vm_rss_kb():
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except FileNotFoundError:
        pass
    return None


def cpu_times():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime, r.ru_stime


def make_engine(now_holder, heartbeat_timeout=2.0, ttl=15.0):
    config = BridgeConfig(
        api_key=API_KEY, allowed_symbols=(SYMBOL,), magic_number=MAGIC,
        max_lot_size=5.0, max_slippage_points=20,
        heartbeat_timeout_seconds=heartbeat_timeout, command_ttl_seconds=ttl,
    )
    queue = CommandQueue(config)
    health = ConnectionHealth(config, clock=lambda: now_holder[0])
    metrics = BridgeMetrics()
    engine = BridgeEngine(config, queue, health, clock=lambda: now_holder[0], metrics=metrics)
    return config, engine, queue, health, metrics


def start_server(engine, config, now_holder):
    server = serve(engine, config, clock=lambda: now_holder[0], host="127.0.0.1", port=0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, port


def http_post(port, path, payload, api_key=API_KEY, timeout=5):
    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        headers[API_KEY_HEADER] = api_key
    data = json.dumps(payload).encode() if payload is not None else b""
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def http_post_raw(port, path, raw_body_str, api_key=API_KEY, timeout=5):
    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        headers[API_KEY_HEADER] = api_key
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=raw_body_str.encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def http_get(port, path, api_key=API_KEY, timeout=5):
    headers = {}
    if api_key is not None:
        headers[API_KEY_HEADER] = api_key
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def raw_socket_connect_only(port, timeout=3):
    """Simulates 'connection timeout' / unreachable server -- point at a
    port nothing listens on, confirm the client observes a clean refusal
    rather than a hang."""
    try:
        socket.create_connection(("127.0.0.1", port + 1), timeout=timeout)
        return "connected"
    except (ConnectionRefusedError, socket.timeout, OSError) as exc:
        return f"refused_or_timeout: {type(exc).__name__}"


def raw_socket_slow_post(port, path, body_bytes, delay_between_chunks=0.3, chunks=5):
    """A deliberately slow client -- connects, sends headers, then
    dribbles the body out over several seconds. Proves the server
    doesn't block other clients while serving a slow one."""
    sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    try:
        headers = (
            f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
            f"{API_KEY_HEADER}: {API_KEY}\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\nConnection: close\r\n\r\n"
        ).encode()
        sock.sendall(headers)
        chunk_size = max(1, len(body_bytes) // chunks)
        for i in range(0, len(body_bytes), chunk_size):
            sock.sendall(body_bytes[i:i + chunk_size])
            time.sleep(delay_between_chunks)
        sock.settimeout(20)
        response = sock.recv(4096)
        return response
    finally:
        sock.close()


def phase_long_duration(port, duration_seconds=60, sample_interval=2):
    samples = []
    latencies = []
    stop_flag = threading.Event()

    def load_generator(i0):
        i = i0
        while not stop_flag.is_set():
            start = time.perf_counter()
            http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
            latencies.append(time.perf_counter() - start)
            http_post(port, "/bridge/account", {"magic_number": MAGIC, "balance": 10000.0 + i, "equity": 10500.0 + i})
            http_post(port, "/bridge/positions", {
                "magic_number": MAGIC,
                "positions": [{"position_id": f"p{i % 20}", "symbol": SYMBOL, "direction": "BUY", "volume": 0.1, "open_price": 1.1}],
            })
            http_get(port, f"/bridge/commands/poll?magic_number={MAGIC}")
            i += 1
            time.sleep(0.02)

    gen_threads = [threading.Thread(target=load_generator, args=(i * 100000,), daemon=True) for i in range(8)]
    for t in gen_threads:
        t.start()

    thread_counts = []
    start_time = time.time()
    start_cpu = cpu_times()
    start_rss = vm_rss_kb()
    while time.time() - start_time < duration_seconds:
        samples.append({"t": round(time.time() - start_time, 1), "rss_kb": vm_rss_kb(), "threads": threading.active_count()})
        thread_counts.append(threading.active_count())
        time.sleep(sample_interval)
    stop_flag.set()
    for t in gen_threads:
        t.join(timeout=5)
    end_cpu = cpu_times()
    end_rss = vm_rss_kb()

    return {
        "duration_seconds": duration_seconds,
        "samples": samples,
        "rss_start_kb": start_rss,
        "rss_end_kb": end_rss,
        "rss_delta_kb": (end_rss - start_rss) if (start_rss and end_rss) else None,
        "cpu_user_seconds": round(end_cpu[0] - start_cpu[0], 3),
        "cpu_sys_seconds": round(end_cpu[1] - start_cpu[1], 3),
        "thread_count_min": min(thread_counts) if thread_counts else None,
        "thread_count_max": max(thread_counts) if thread_counts else None,
        "requests_sent_approx": len(latencies) * 4,
        "latency_p50_ms": round(statistics.median(latencies) * 1000, 3) if latencies else None,
        "latency_p99_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.99) - 1)] * 1000, 3) if latencies else None,
        "latency_max_ms": round(max(latencies) * 1000, 3) if latencies else None,
    }


def phase_network_recovery(port, engine, config, now_holder):
    out = {}
    # 2a. Network interruption: let heartbeat_timeout_seconds elapse
    #     with no traffic; verify fail-closed.
    now_holder[0] = now_holder[0] + timedelta(seconds=config.heartbeat_timeout_seconds + 1.0)
    out["ready_during_network_gap"] = engine.is_connection_healthy
    cmd = TradeCommand(
        schema_version=SCHEMA_VERSION, correlation_id="net-gap-1", command_kind=CommandKind.BUY,
        symbol=SYMBOL, volume=0.1, stop_loss=1.09, take_profit=1.11, position_id=None,
        close_volume=None, magic_number=MAGIC, max_slippage_points=20, issued_at=now_holder[0],
    )
    reason_during_gap = engine.submit_command(cmd, now_holder[0])
    out["submit_rejected_during_gap"] = reason_during_gap.value if reason_during_gap else None

    # 2b. Network restoration: resume heartbeats via real HTTP, verify recovery.
    status, _ = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
    out["heartbeat_restore_http_status"] = status
    out["ready_after_restore"] = engine.is_connection_healthy
    reason_after_restore = engine.submit_command(cmd, now_holder[0])
    out["submit_accepted_after_restore"] = reason_after_restore  # None means accepted
    reason_duplicate = engine.submit_command(cmd, now_holder[0])
    out["duplicate_correlation_id_rejected_as"] = reason_duplicate.value if reason_duplicate else None

    # 2c. Delayed packets: a deliberately slow client must not block
    #     concurrent fast clients.
    fast_results = []
    slow_result_holder = {}

    def fast_client(i):
        status, _ = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
        fast_results.append(status)

    def slow_client():
        body = json.dumps({"magic_number": MAGIC, "terminal_connected": True}).encode()
        try:
            resp = raw_socket_slow_post(port, "/bridge/heartbeat", body, delay_between_chunks=0.4, chunks=4)
            slow_result_holder["response_prefix"] = resp[:20].decode(errors="replace")
        except Exception as exc:
            slow_result_holder["error"] = str(exc)

    slow_thread = threading.Thread(target=slow_client)
    slow_thread.start()
    time.sleep(0.1)
    fast_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(fast_client, range(20)))
    fast_elapsed = time.perf_counter() - fast_start
    slow_thread.join(timeout=10)

    out["slow_client_result"] = slow_result_holder
    out["fast_clients_all_200_while_slow_client_in_flight"] = all(s == 200 for s in fast_results)
    out["fast_clients_elapsed_seconds"] = round(fast_elapsed, 3)
    out["fast_clients_not_blocked_by_slow_client"] = fast_elapsed < 1.5  # generous bound

    # 2d. Connection timeout: point at a port nothing listens on.
    out["connection_timeout_behavior"] = raw_socket_connect_only(port)
    return out


def phase_mt5_recovery_proxy(engine, config, now_holder):
    """Bridge-observable proxy for 'MT5 restart' / 'EA reconnect' /
    'Terminal unavailable': EA-side traffic (heartbeats) stops for a
    window, then resumes. What the bridge can prove: fail-closed during
    the outage, no duplicate execution once traffic resumes, and state
    consistency (no commands invented or lost)."""
    out = {}
    base_time = now_holder[0]

    # Simulate the EA going away: no heartbeat for well past the timeout.
    now_holder[0] = base_time + timedelta(seconds=config.heartbeat_timeout_seconds * 5)
    out["ready_during_simulated_terminal_outage"] = engine.is_connection_healthy

    cmd = TradeCommand(
        schema_version=SCHEMA_VERSION, correlation_id="mt5-outage-1", command_kind=CommandKind.SELL,
        symbol=SYMBOL, volume=0.2, stop_loss=1.12, take_profit=1.08, position_id=None,
        close_volume=None, magic_number=MAGIC, max_slippage_points=20, issued_at=now_holder[0],
    )
    out["submit_during_outage_rejected_as"] = engine.submit_command(cmd, now_holder[0])
    if out["submit_during_outage_rejected_as"] is not None:
        out["submit_during_outage_rejected_as"] = out["submit_during_outage_rejected_as"].value

    # Simulate EA/terminal reconnecting.
    from titan_protocol.bridge.models import HeartbeatMessage
    engine.handle_heartbeat(HeartbeatMessage(
        schema_version=SCHEMA_VERSION, magic_number=MAGIC, account_login=12345,
        terminal_connected=True, received_at=now_holder[0],
    ))
    out["ready_after_simulated_reconnect"] = engine.is_connection_healthy

    reason = engine.submit_command(cmd, now_holder[0])
    out["submit_after_reconnect_accepted"] = reason is None
    delivered = engine.poll_commands(now_holder[0])
    out["delivered_after_reconnect_count"] = len(delivered)
    out["delivered_ids_unique"] = len({c.correlation_id for c in delivered}) == len(delivered)

    # No duplicated execution: report the same command's result twice.
    from titan_protocol.bridge.models import ExecutionReport
    report = ExecutionReport(
        schema_version=SCHEMA_VERSION, correlation_id="mt5-outage-1", magic_number=MAGIC,
        success=True, broker_ticket="t-outage-1", filled_price=1.1, filled_volume=0.2,
        error_code=None, reported_at=now_holder[0],
    )
    first = engine.handle_execution_report(report)
    second = engine.handle_execution_report(report)
    out["first_report_recorded"] = first
    out["duplicate_report_not_recorded_twice"] = (first is True and second is False)
    return out


def phase_python_recovery_proxy(now_holder):
    """Proxy for 'Bridge restart / HTTP server restart / process
    restart': Phase 1 has no cross-process persistence by design (no
    spec ever promised it), so a fresh process starts with empty state.
    What matters for production-readiness: the fresh instance comes up
    cleanly, accepts heartbeats immediately, and behaves identically to
    a first-ever boot -- not that in-flight state survives, which was
    never a requirement."""
    out = {}
    config2, engine2, queue2, health2, metrics2 = make_engine(now_holder)
    server2, thread2, port2 = start_server(engine2, config2, now_holder)
    try:
        out["fresh_instance_starts_not_ready"] = not engine2.is_connection_healthy
        status, body = http_post(port2, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
        out["fresh_instance_accepts_heartbeat_status"] = status
        out["fresh_instance_ready_after_heartbeat"] = engine2.is_connection_healthy
        status, body = http_get(port2, f"/bridge/commands/poll?magic_number={MAGIC}")
        out["fresh_instance_poll_status"] = status
        out["fresh_instance_poll_commands_empty"] = body.get("commands") == []
    finally:
        server2.shutdown()
        server2.server_close()
        thread2.join(timeout=5)
    return out


def phase_broker_recovery_proxy(port, now_holder):
    """Proxy for 'Broker disconnect/reconnect, market closed, symbol
    unavailable': these retcodes are handled MQL5-side (untestable
    without real MetaEditor/MT5); what the BRIDGE owns is accepting and
    recording the EA's error report for these conditions correctly."""
    out = {}
    scenarios = [
        ("MARKET_CLOSED_OR_NO_QUOTES", "no quotes for EURUSD"),
        ("SYMBOL_NOT_AVAILABLE", "symbol select failed"),
        ("10018", "TRADE_RETCODE_MARKET_CLOSED"),
        ("10031", "TRADE_RETCODE_CONNECTION (broker disconnect)"),
    ]
    recorded = []
    for code, message in scenarios:
        status, body = http_post(port, "/bridge/error", {
            "magic_number": MAGIC, "error_code": code, "message": message,
        })
        recorded.append({"code": code, "status": status})
    out["error_reports_accepted"] = all(r["status"] == 200 for r in recorded)
    out["scenarios"] = recorded
    return out


def phase_stress(port):
    out = {}
    errors = []
    errors_lock = threading.Lock()
    symbols_seen = set()

    def poller(_):
        try:
            for _ in range(50):
                status, body = http_get(port, f"/bridge/commands/poll?magic_number={MAGIC}")
                if status != 200:
                    with errors_lock:
                        errors.append(f"poll status {status}")
        except Exception as exc:
            with errors_lock:
                errors.append(str(exc))

    def reporter(i):
        try:
            for j in range(50):
                cid = f"stress-{i}-{j}"
                status, body = http_post(port, "/bridge/execution/report", {
                    "correlation_id": cid, "magic_number": MAGIC, "success": True,
                    "broker_ticket": f"t-{cid}", "filled_price": 1.1, "filled_volume": 0.1,
                })
                if status != 200:
                    with errors_lock:
                        errors.append(f"report status {status}")
        except Exception as exc:
            with errors_lock:
                errors.append(str(exc))

    def heartbeater(i):
        try:
            for _ in range(50):
                status, _ = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
                if status != 200:
                    with errors_lock:
                        errors.append(f"heartbeat status {status}")
        except Exception as exc:
            with errors_lock:
                errors.append(str(exc))

    thread_count = 60
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=thread_count) as pool:
        futures = []
        futures += [pool.submit(poller, i) for i in range(thread_count // 3)]
        futures += [pool.submit(reporter, i) for i in range(thread_count // 3)]
        futures += [pool.submit(heartbeater, i) for i in range(thread_count // 3)]
        for f in futures:
            f.result()
    elapsed = time.perf_counter() - start

    out["thread_count"] = thread_count
    out["elapsed_seconds"] = round(elapsed, 3)
    out["errors"] = errors
    out["no_errors"] = errors == []
    out["approx_requests"] = thread_count * 50
    out["approx_throughput_rps"] = round((thread_count * 50) / elapsed, 1)
    return out


def phase_security(port):
    out = {}
    # Invalid API key
    status, body = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC}, api_key="wrong-key")
    out["invalid_api_key_status"] = status
    status, body = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC}, api_key=None)
    out["missing_api_key_status"] = status

    # Invalid JSON
    status, body = http_post_raw(port, "/bridge/heartbeat", "{not valid json", api_key=API_KEY)
    out["invalid_json_status"] = status

    # Duplicate execution report / replay
    status1, body1 = http_post(port, "/bridge/execution/report", {
        "correlation_id": "sec-dup-1", "magic_number": MAGIC, "success": True,
        "broker_ticket": "t-sec-1", "filled_price": 1.1, "filled_volume": 0.1,
    })
    status2, body2 = http_post(port, "/bridge/execution/report", {
        "correlation_id": "sec-dup-1", "magic_number": MAGIC, "success": True,
        "broker_ticket": "t-sec-1", "filled_price": 1.1, "filled_volume": 0.1,
    })
    out["first_execution_report_status"] = status1
    out["duplicate_execution_report_status"] = status2
    out["duplicate_execution_report_recorded_flag"] = body2.get("recorded")

    # Replay of an identical heartbeat / positions payload (should just
    # be accepted repeatedly -- heartbeats are not single-use, unlike
    # execution reports; confirms the two are NOT conflated).
    r1, _ = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
    r2, _ = http_post(port, "/bridge/heartbeat", {"magic_number": MAGIC, "terminal_connected": True})
    out["heartbeat_replay_both_accepted"] = (r1 == 200 and r2 == 200)

    # Invalid "command" shape: magic number mismatch on a route
    status, body = http_post(port, "/bridge/account", {"magic_number": 999999, "balance": 1.0, "equity": 1.0})
    out["magic_number_mismatch_status"] = status
    out["magic_number_mismatch_error"] = body.get("error")

    # Missing required field
    status, body = http_post(port, "/bridge/account", {"magic_number": MAGIC})
    out["missing_required_field_status"] = status

    # Unauthorized administrative action: emergency-stop without API key
    status, body = http_post(port, "/bridge/emergency-stop", {"active": True}, api_key=None)
    out["unauthorized_emergency_stop_status"] = status
    status, body = http_post(port, "/bridge/emergency-stop", {"active": True}, api_key="wrong-key")
    out["wrong_key_emergency_stop_status"] = status
    # Authorized version, then deactivate (for the observability phase to see both events)
    status, body = http_post(port, "/bridge/emergency-stop", {"active": True, "reason": "phase1_5-security-check"})
    out["authorized_emergency_stop_status"] = status
    status, body = http_post(port, "/bridge/emergency-stop", {"active": False})
    out["authorized_emergency_stop_deactivate_status"] = status

    # Unknown route
    status, body = http_get(port, "/bridge/does-not-exist")
    out["unknown_route_status"] = status
    return out


def phase_observability():
    out = {}
    events = {}
    for rec in log_records:
        events.setdefault(rec.msg, []).append(rec)

    required = {
        "correlation_id_present": any(
            "correlation_id" in getattr(r, "__dict__", {}) for msgs in events.values() for r in msgs
        ),
        "heartbeat_events_logged": "bridge.heartbeat" in events,
        "execution_result_events_logged": "bridge.execution_report" in events,
        "emergency_stop_activation_logged": any(
            getattr(r, "active", None) is True for r in events.get("bridge.emergency_stop", [])
        ),
        "emergency_stop_deactivation_logged": any(
            getattr(r, "active", None) is False for r in events.get("bridge.emergency_stop", [])
        ),
        "error_report_events_logged": "bridge.error_report" in events,
    }
    out["event_types_seen"] = sorted(events.keys())
    out["event_counts"] = {k: len(v) for k, v in events.items()}
    out["checks"] = required
    out["total_log_records_captured"] = len(log_records)
    return out


def main():
    now_holder = [datetime(2026, 7, 10, 0, 0, 0, tzinfo=timezone.utc)]
    config, engine, queue, health, metrics = make_engine(now_holder)

    root_logger = logging.getLogger("titan_protocol.bridge")
    root_logger.setLevel(logging.DEBUG)
    handler = _CapturingHandler()
    root_logger.addHandler(handler)

    server, thread, port = start_server(engine, config, now_holder)
    results["port"] = port
    print(f"[setup] server started on port {port}")

    try:
        results["long_duration"] = phase_long_duration(port, duration_seconds=60, sample_interval=2)
        print("[phase1] long-duration load complete")

        results["network_recovery"] = phase_network_recovery(port, engine, config, now_holder)
        print("[phase2] network recovery complete")

        results["mt5_recovery_proxy"] = phase_mt5_recovery_proxy(engine, config, now_holder)
        print("[phase3] MT5/terminal-outage proxy complete")

        results["broker_recovery_proxy"] = phase_broker_recovery_proxy(port, now_holder)
        print("[phase5] broker-recovery proxy complete")

        results["stress"] = phase_stress(port)
        print("[phase6] stress complete")

        results["security"] = phase_security(port)
        print("[phase7] security complete")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # Python-restart proxy runs its own fresh server instance, after the
    # first one has been shut down cleanly.
    results["python_recovery_proxy"] = phase_python_recovery_proxy(now_holder)
    print("[phase4] python-restart proxy complete")

    results["observability"] = phase_observability()
    print("[phase8] observability complete")

    root_logger.removeHandler(handler)


if __name__ == "__main__":
    import os

    main()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "phase1_5_results.json")
    with open(output_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n=== RESULTS (also written to {output_path}) ===")
    print(json.dumps(results, indent=2, default=str))
