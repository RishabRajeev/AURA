"""
AURA Monitor - Fatigue Signature & Context-Switch Tracker

Tracks:
1. Fatigue Signature: Keystroke latency (std dev), Error Rate Proxy (backspaces)
2. Context-Switch Tracking: App/window switching frequency

All data stays local. No telemetry.
"""

import time
import threading
import statistics
from collections import deque
from dataclasses import dataclass
from typing import Optional, Any

try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

try:
    import pywinctl
    WINDOW_AVAILABLE = True
except ImportError:
    try:
        import pygetwindow
        pywinctl = pygetwindow
        WINDOW_AVAILABLE = True
    except ImportError:
        WINDOW_AVAILABLE = False


@dataclass
class FatigueMetrics:
    """Real-time fatigue signature metrics."""
    keystroke_latency_std: float = 0.0
    keystroke_latency_mean: float = 0.0
    error_rate_proxy: float = 0.0  # backspaces / total_keys
    total_keystrokes: int = 0
    backspace_count: int = 0
    context_switches_per_min: float = 0.0
    last_window: str = ""
    fatigue_score: float = 0.0  # 0-100, higher = more fatigued
    is_baseline_mode: bool = False


class FatigueSignatureTracker:
    """
    Tracks keystroke timing to compute the Fatigue Signature.
    
    Fatigue indicators:
    - Rising std dev of latency = inconsistent motor control (cognitive decay)
    - High backspace ratio = error rate proxy
    """

    WINDOW_SIZE = 50  # keystrokes for rolling stats
    MIN_SAMPLES = 10  # minimum before computing std dev

    def __init__(self):
        self._latencies: deque[float] = deque(maxlen=self.WINDOW_SIZE)
        self._last_key_time: Optional[float] = None
        self._total_keys = 0
        self._backspace_count = 0
        self._lock = threading.Lock()

    def _is_backspace(self, key) -> bool:
        if not PYNPUT_AVAILABLE:
            return False
        return key in (keyboard.Key.backspace, keyboard.Key.delete)

    def on_press(self, key):
        """Called on each keypress by pynput."""
        try:
            now = time.perf_counter()
            with self._lock:
                self._total_keys += 1
                if self._is_backspace(key):
                    self._backspace_count += 1
                if self._last_key_time is not None:
                    delta_ms = (now - self._last_key_time) * 1000
                    if 20 < delta_ms < 2000:  # filter outliers (pauses, long gaps)
                        self._latencies.append(delta_ms)
                self._last_key_time = now
        except Exception:
            pass

    def get_metrics(self) -> tuple[float, float, float]:
        """
        Returns (latency_std_ms, latency_mean_ms, error_rate_proxy).
        """
        with self._lock:
            n = len(self._latencies)
            total = self._total_keys
            backspaces = self._backspace_count

        if n < self.MIN_SAMPLES:
            return 0.0, 0.0, 0.0

        std_ms = statistics.stdev(self._latencies)
        mean_ms = statistics.mean(self._latencies)
        error_rate = backspaces / total if total > 0 else 0.0

        return std_ms, mean_ms, error_rate

    def get_raw_counts(self) -> tuple[int, int]:
        return self._total_keys, self._backspace_count


class ContextSwitchTracker:
    """
    Tracks application/window switches to detect fragmented attention.
    """

    def __init__(self, window_size_sec: float = 60.0):
        self._window_sec = window_size_sec
        self._switches: deque[float] = deque()
        self._last_window: str = ""
        self._lock = threading.Lock()

    def _get_active_window_title(self) -> str:
        if not WINDOW_AVAILABLE:
            return "unknown"
        try:
            win = pywinctl.getActiveWindow()
            return win.title if win and win.title else "unknown"
        except Exception:
            return "unknown"

    def poll(self):
        """Call periodically (e.g., every 2s) to check for context switch."""
        title = self._get_active_window_title()
        with self._lock:
            if title and title != self._last_window:
                self._last_window = title
                self._switches.append(time.time())
            self._prune_old()

    def _prune_old(self):
        cutoff = time.time() - self._window_sec
        while self._switches and self._switches[0] < cutoff:
            self._switches.popleft()

    def get_switches_per_minute(self) -> float:
        with self._lock:
            self._prune_old()
            count = len(self._switches)
        return (count / self._window_sec) * 60.0 if self._window_sec > 0 else 0.0

    def get_last_window(self) -> str:
        with self._lock:
            return self._last_window or self._get_active_window_title()


class AuraMonitor:
    """
    Main monitor combining Fatigue Signature and Context-Switch tracking.
    """

    def __init__(self, baseline_mode_minutes: int = 30):
        self.fatigue = FatigueSignatureTracker()
        self.context = ContextSwitchTracker(window_size_sec=60.0)
        self._baseline_minutes = baseline_mode_minutes
        self._session_start = time.time()
        self._baseline_latency_std: Optional[float] = None
        self._baseline_error_rate: Optional[float] = None
        self._listener: Any = None
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False

    def _is_baseline_mode(self) -> bool:
        elapsed_min = (time.time() - self._session_start) / 60.0
        return elapsed_min < self._baseline_minutes and self._baseline_latency_std is None

    def _update_baseline_if_needed(self, std_ms: float, error_rate: float):
        if not self._is_baseline_mode():
            return
        elapsed_min = (time.time() - self._session_start) / 60.0
        if elapsed_min >= self._baseline_minutes:
            self._baseline_latency_std = std_ms
            self._baseline_error_rate = error_rate

    def _compute_fatigue_score(
        self,
        std_ms: float,
        error_rate: float,
        switches_per_min: float
    ) -> float:
        """
        Compute 0-100 fatigue score from deviation from baseline + context switches.
        """
        if self._is_baseline_mode():
            return 0.0

        score = 0.0

        # Latency std dev: rising = fatigue
        if self._baseline_latency_std and self._baseline_latency_std > 0:
            ratio = std_ms / self._baseline_latency_std
            if ratio > 1.2:
                score += min(40, (ratio - 1.2) * 50)
        else:
            if std_ms > 80:
                score += min(30, (std_ms - 80) / 2)

        # Error rate
        if self._baseline_error_rate is not None and self._baseline_error_rate > 0:
            err_ratio = error_rate / self._baseline_error_rate
            if err_ratio > 1.5:
                score += min(30, (err_ratio - 1.5) * 30)
        else:
            if error_rate > 0.15:
                score += min(25, error_rate * 100)

        # Context switching (fragmented attention)
        if switches_per_min > 8:
            score += min(30, (switches_per_min - 8) * 2)

        return min(100.0, score)

    def get_metrics(self) -> FatigueMetrics:
        std_ms, mean_ms, error_rate = self.fatigue.get_metrics()
        switches_per_min = self.context.get_switches_per_minute()
        last_window = self.context.get_last_window()

        self._update_baseline_if_needed(std_ms, error_rate)
        fatigue_score = self._compute_fatigue_score(std_ms, error_rate, switches_per_min)

        total, backspaces = self.fatigue.get_raw_counts()

        return FatigueMetrics(
            keystroke_latency_std=round(std_ms, 2),
            keystroke_latency_mean=round(mean_ms, 2),
            error_rate_proxy=round(error_rate, 4),
            total_keystrokes=total,
            backspace_count=backspaces,
            context_switches_per_min=round(switches_per_min, 2),
            last_window=last_window[:80] if last_window else "",
            fatigue_score=round(fatigue_score, 2),
            is_baseline_mode=self._is_baseline_mode(),
        )

    def _poll_loop(self):
        while self._running:
            self.context.poll()
            time.sleep(2.0)

    def start(self):
        """Start keystroke listener and context-switch poller."""
        self._running = True
        if PYNPUT_AVAILABLE:
            self._listener = keyboard.Listener(on_press=self.fatigue.on_press)
            self._listener.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self):
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        if self._poll_thread:
            self._poll_thread.join(timeout=3.0)
