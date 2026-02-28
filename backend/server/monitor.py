"""
AURA Monitor - Fatigue Signature, Context-Switch, Micro-Scroll, Cognitive Load,
Idle Detection, Session Duration, Time-of-Day, Hold Duration.

Tracks:
1. Fatigue Signature: Keystroke latency (std dev), Error Rate Proxy (backspaces)
2. Context-Switch Tracking: App/window switching frequency
3. Micro-Scroll Trap: Zombie-mode scrolling
4. Cognitive Load Index: App categorization for fuel gauge
5. Idle/Absence Detection: No input for 10+ min while focused
6. Session Duration: Active time today
7. Time-of-Day Weighting: Late night = stronger fatigue signal
8. Hold Duration: Key press-to-release timing (motor fatigue)

All data stays local. No telemetry.
"""

import time
import threading
import statistics
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Any, Callable

try:
    from pynput import keyboard, mouse
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
    error_rate_proxy: float = 0.0
    total_keystrokes: int = 0
    backspace_count: int = 0
    context_switches_per_min: float = 0.0
    last_window: str = ""
    fatigue_score: float = 0.0
    is_baseline_mode: bool = False
    cognitive_load_index: float = 0.0
    cognitive_load_label: str = "unknown"
    micro_scroll_trap_detected: bool = False
    scroll_rate_per_min: float = 0.0
    fuel_gauge: float = 100.0
    # New detection fields
    idle_detected: bool = False
    idle_minutes: float = 0.0
    session_active_minutes: float = 0.0
    hold_duration_mean_ms: float = 0.0
    hold_duration_std_ms: float = 0.0
    time_of_day_factor: float = 1.0


# ---- Cognitive Load (expanded keywords + user overrides) ----
HIGH_LOAD_KEYWORDS = [
    "code", "visual studio", "vscode", "cursor", "jetbrains", "pycharm",
    "intellij", "xcode", "sublime", "vim", "emacs", "terminal", "cmd",
    "notepad++", "atom", "eclipse", "writing", "scrivener", "latex",
    "notion", "obsidian", "roam", "logseq", "jupyter", "spyder",
    "matlab", "rstudio", "datagrip", "dbeaver", "postman", "insomnia",
]
PASSIVE_KEYWORDS = [
    "youtube", "netflix", "twitter", "x.com", "instagram", "tiktok",
    "facebook", "reddit", "twitch", "spotify", "music", "pinterest",
    "tumblr", "snapchat", "whatsapp web", "telegram web",
]
MEDIUM_LOAD_KEYWORDS = [
    "slack", "discord", "teams", "zoom", "gmail", "outlook", "thunderbird",
    "chrome", "firefox", "edge", "safari", "brave", "arc", "browser",
    "calendar", "drive", "docs", "sheets", "figma", "miro", "mural",
]


def _classify_cognitive_load(window_title: str, user_overrides: Optional[dict] = None) -> tuple[float, str]:
    """User overrides: { "app name or partial match": "high"|"medium"|"passive" }"""
    if not window_title or window_title == "unknown":
        return 0.5, "unknown"
    lower = window_title.lower()

    if user_overrides:
        for pattern, load in user_overrides.items():
            if pattern.lower() in lower:
                load = str(load).lower()
                if load == "high":
                    return 0.9, "high"
                if load == "passive":
                    return 0.2, "passive"
                if load == "medium":
                    return 0.5, "medium"

    for kw in HIGH_LOAD_KEYWORDS:
        if kw in lower:
            return 0.9, "high"
    for kw in PASSIVE_KEYWORDS:
        if kw in lower:
            return 0.2, "passive"
    for kw in MEDIUM_LOAD_KEYWORDS:
        if kw in lower:
            return 0.5, "medium"
    return 0.6, "neutral"


def _get_time_of_day_factor() -> float:
    """1.0 = normal, 1.2–1.4 = late night / early morning (circadian low)."""
    hour = datetime.now().hour
    if 6 <= hour < 10:
        return 1.05
    if 10 <= hour < 18:
        return 1.0
    if 18 <= hour < 22:
        return 1.05
    return 1.25


def _is_modifier_key(key) -> bool:
    """Exclude modifier key timing from typing rhythm — chord combos distort latency."""
    if not PYNPUT_AVAILABLE:
        return False
    mods = (
        keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
        keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r,
        keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
        keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
    )
    return key in mods


class FatigueSignatureTracker:
    WINDOW_SIZE = 50
    MIN_SAMPLES = 10

    def __init__(self):
        self._latencies: deque[float] = deque(maxlen=self.WINDOW_SIZE)
        self._last_key_time: Optional[float] = None
        self._last_key: Any = None
        self._total_keys = 0
        self._backspace_count = 0
        self._lock = threading.Lock()

    def _is_backspace(self, key) -> bool:
        if not PYNPUT_AVAILABLE:
            return False
        return key in (keyboard.Key.backspace, keyboard.Key.delete)

    def on_press(self, key):
        try:
            now = time.perf_counter()
            with self._lock:
                self._total_keys += 1
                if self._is_backspace(key):
                    self._backspace_count += 1
                if self._last_key_time is not None:
                    skip = _is_modifier_key(key) or _is_modifier_key(self._last_key)
                    if not skip:
                        delta_ms = (now - self._last_key_time) * 1000
                        if 20 < delta_ms < 2000:
                            self._latencies.append(delta_ms)
                self._last_key_time = now
                self._last_key = key
        except Exception:
            pass

    def get_metrics(self) -> tuple[float, float, float]:
        with self._lock:
            total = self._total_keys
            backspaces = self._backspace_count

        if len(self._latencies) < self.MIN_SAMPLES:
            return 0.0, 0.0, 0.0

        std_ms = statistics.stdev(self._latencies)
        mean_ms = statistics.mean(self._latencies)
        error_rate = backspaces / total if total > 0 else 0.0
        return std_ms, mean_ms, error_rate

    def get_raw_counts(self) -> tuple[int, int]:
        return self._total_keys, self._backspace_count


class HoldDurationTracker:
    """
    Key press-to-release timing. Long or inconsistent holds can indicate motor fatigue.
    """

    WINDOW_SIZE = 50
    MIN_SAMPLES = 5
    MAX_HOLD_MS = 2000

    def __init__(self):
        self._press_times: dict = {}
        self._hold_durations: deque[float] = deque(maxlen=self.WINDOW_SIZE)
        self._lock = threading.Lock()

    def on_press(self, key):
        try:
            with self._lock:
                self._press_times[key] = time.perf_counter()
        except Exception:
            pass

    def on_release(self, key):
        try:
            with self._lock:
                if key in self._press_times:
                    dt = (time.perf_counter() - self._press_times[key]) * 1000
                    del self._press_times[key]
                    if 10 < dt < self.MAX_HOLD_MS:
                        self._hold_durations.append(dt)
        except Exception:
            pass

    def get_metrics(self) -> tuple[float, float]:
        with self._lock:
            n = len(self._hold_durations)
        if n < self.MIN_SAMPLES:
            return 0.0, 0.0
        mean_ms = statistics.mean(self._hold_durations)
        std_ms = statistics.stdev(self._hold_durations)
        return mean_ms, std_ms


class ContextSwitchTracker:
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


class MicroScrollTrapTracker:
    WINDOW_SEC = 120
    SCROLL_THRESHOLD = 25

    def __init__(self):
        self._scrolls: deque[float] = deque()
        self._lock = threading.Lock()

    def on_scroll(self, x, y, dx, dy):
        with self._lock:
            self._scrolls.append(time.time())

    def on_key_or_click(self):
        pass

    def _prune_old(self):
        cutoff = time.time() - self.WINDOW_SEC
        while self._scrolls and self._scrolls[0] < cutoff:
            self._scrolls.popleft()

    def get_scroll_rate_per_min(self) -> float:
        with self._lock:
            self._prune_old()
            count = len(self._scrolls)
        return (count / self.WINDOW_SEC) * 60.0 if self.WINDOW_SEC > 0 else 0.0

    def is_trap_detected(self) -> bool:
        return self.get_scroll_rate_per_min() >= self.SCROLL_THRESHOLD


class IdleTracker:
    """
    No keystroke, scroll, or click for 10+ minutes = "zoning out" or deep reading.
    """

    IDLE_THRESHOLD_SEC = 600  # 10 min

    def __init__(self):
        self._last_activity = time.time()
        self._lock = threading.Lock()

    def on_activity(self):
        with self._lock:
            self._last_activity = time.time()

    def get_idle_minutes(self) -> float:
        with self._lock:
            elapsed = time.time() - self._last_activity
        return elapsed / 60.0

    def is_idle_detected(self) -> bool:
        return self.get_idle_minutes() >= (self.IDLE_THRESHOLD_SEC / 60.0)


class AuraMonitor:
    def __init__(
        self,
        baseline_mode_minutes: int = 5,
        baseline_latency_std: Optional[float] = None,
        baseline_error_rate: Optional[float] = None,
        cognitive_load_overrides: Optional[Callable[[], dict]] = None,
    ):
        self.fatigue = FatigueSignatureTracker()
        self.hold_duration = HoldDurationTracker()
        self.context = ContextSwitchTracker(window_size_sec=60.0)
        self.micro_scroll = MicroScrollTrapTracker()
        self.idle = IdleTracker()
        self._baseline_minutes = baseline_mode_minutes
        self._session_start = time.time()
        self._baseline_latency_std = baseline_latency_std
        self._baseline_error_rate = baseline_error_rate
        self._baseline_hold_std: Optional[float] = None
        self._get_cognitive_overrides = cognitive_load_overrides or (lambda: {})
        self._on_baseline_complete: Optional[Callable[[float, float], None]] = None
        self._listener: Any = None
        self._mouse_listener: Any = None
        self._poll_thread: Optional[threading.Thread] = None
        self._running = False

    def _is_baseline_mode(self) -> bool:
        elapsed_min = (time.time() - self._session_start) / 60.0
        return elapsed_min < self._baseline_minutes and self._baseline_latency_std is None

    def _update_baseline_if_needed(self, std_ms: float, error_rate: float, hold_std: float):
        if not self._is_baseline_mode():
            return
        elapsed_min = (time.time() - self._session_start) / 60.0
        if elapsed_min >= self._baseline_minutes:
            self._baseline_latency_std = std_ms
            self._baseline_error_rate = error_rate
            self._baseline_hold_std = hold_std if hold_std > 0 else None
            if self._on_baseline_complete:
                self._on_baseline_complete(std_ms, error_rate)

    def _compute_fatigue_score(
        self,
        std_ms: float,
        error_rate: float,
        switches_per_min: float,
        micro_scroll_trap: bool,
        idle_detected: bool,
        session_minutes: float,
        hold_std_ms: float,
        time_factor: float,
    ) -> float:
        if self._is_baseline_mode():
            return 0.0

        score = 0.0

        if self._baseline_latency_std and self._baseline_latency_std > 0:
            ratio = std_ms / self._baseline_latency_std
            if ratio > 1.2:
                score += min(30, (ratio - 1.2) * 50)
        else:
            if std_ms > 80:
                score += min(20, (std_ms - 80) / 2)

        if self._baseline_error_rate is not None and self._baseline_error_rate > 0:
            err_ratio = error_rate / self._baseline_error_rate
            if err_ratio > 1.5:
                score += min(20, (err_ratio - 1.5) * 30)
        else:
            if error_rate > 0.15:
                score += min(15, error_rate * 100)

        if switches_per_min > 8:
            score += min(20, (switches_per_min - 8) * 2)

        if micro_scroll_trap:
            score += 12

        if idle_detected:
            score += 10

        if session_minutes > 120:
            score += min(15, (session_minutes - 120) / 60 * 5)
        elif session_minutes > 60:
            score += min(8, (session_minutes - 60) / 60 * 4)

        if self._baseline_hold_std and self._baseline_hold_std > 0 and hold_std_ms > 0:
            hold_ratio = hold_std_ms / self._baseline_hold_std
            if hold_ratio > 1.3:
                score += min(10, (hold_ratio - 1.3) * 20)

        return min(100.0, score * time_factor)

    def _compute_fuel_gauge(
        self,
        fatigue_score: float,
        cognitive_load: float,
        session_minutes: float,
    ) -> float:
        base = 100.0
        base -= fatigue_score * 0.35
        base -= cognitive_load * 18
        if session_minutes > 60:
            base -= min(15, (session_minutes - 60) / 60 * 5)
        return max(0.0, min(100.0, base))

    def get_metrics(self) -> FatigueMetrics:
        std_ms, mean_ms, error_rate = self.fatigue.get_metrics()
        hold_mean, hold_std = self.hold_duration.get_metrics()
        switches_per_min = self.context.get_switches_per_minute()
        last_window = self.context.get_last_window()
        overrides = self._get_cognitive_overrides()
        load_index, load_label = _classify_cognitive_load(last_window, overrides)
        scroll_rate = self.micro_scroll.get_scroll_rate_per_min()
        micro_scroll_trap = self.micro_scroll.is_trap_detected()
        idle_min = self.idle.get_idle_minutes()
        idle_det = self.idle.is_idle_detected()
        session_min = (time.time() - self._session_start) / 60.0
        time_factor = _get_time_of_day_factor()

        self._update_baseline_if_needed(std_ms, error_rate, hold_std)
        fatigue_score = self._compute_fatigue_score(
            std_ms, error_rate, switches_per_min, micro_scroll_trap,
            idle_det, session_min, hold_std, time_factor,
        )
        fuel_gauge = self._compute_fuel_gauge(fatigue_score, load_index, session_min)

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
            cognitive_load_index=round(load_index, 2),
            cognitive_load_label=load_label,
            micro_scroll_trap_detected=micro_scroll_trap,
            scroll_rate_per_min=round(scroll_rate, 1),
            fuel_gauge=round(fuel_gauge, 1),
            idle_detected=idle_det,
            idle_minutes=round(idle_min, 1),
            session_active_minutes=round(session_min, 1),
            hold_duration_mean_ms=round(hold_mean, 2),
            hold_duration_std_ms=round(hold_std, 2),
            time_of_day_factor=round(time_factor, 2),
        )

    def _on_key_press(self, key):
        self.fatigue.on_press(key)
        self.hold_duration.on_press(key)
        self.idle.on_activity()

    def _on_key_release(self, key):
        self.hold_duration.on_release(key)

    def _on_scroll(self, x, y, dx, dy):
        self.micro_scroll.on_scroll(x, y, dx, dy)
        self.idle.on_activity()

    def _on_click(self, x, y, button, pressed):
        if pressed:
            self.idle.on_activity()

    def _poll_loop(self):
        while self._running:
            self.context.poll()
            time.sleep(2.0)

    def start(self):
        self._running = True
        if PYNPUT_AVAILABLE:
            self._listener = keyboard.Listener(
                on_press=self._on_key_press,
                on_release=self._on_key_release,
            )
            self._listener.start()
            self._mouse_listener = mouse.Listener(
                on_scroll=self._on_scroll,
                on_click=self._on_click,
            )
            self._mouse_listener.start()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def stop(self):
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None
        if self._poll_thread:
            self._poll_thread.join(timeout=3.0)
