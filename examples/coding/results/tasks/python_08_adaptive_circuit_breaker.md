# Adaptive Circuit Breaker

**Category:** Python / systems coding · `python_08_adaptive_circuit_breaker`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **1** |
| Claude Haiku 4.5 + `/reason` | **4** |
| Delta | **+3** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate B provides a coherent EWMA-based latency trend detector, thread-safe state, and a snapshot API, but it is incomplete (missing core state transitions and update logic), so it cannot run as-is. Candidate A is more incomplete with a syntax error, missing core methods, and unfinished monitoring/state logic, so it fails to meet the runnable and requirements criteria even more severely.

---

## Task
Implement an adaptive circuit breaker for an external API. The API degrades slowly through increased latency rather than outright failures. React to latency trends, not just error counts, automatically adjust thresholds over time, support half-open recovery, and expose the current breaker state.

---

## WITHOUT — Claude Haiku 4.5 alone
# Adaptive Circuit Breaker for Latency-Sensitive APIs

I'll implement a comprehensive circuit breaker that adapts to latency trends and gracefully handles degraded API states.

```python
import asyncio
import time
import statistics
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, Any, Optional, List, Tuple
from collections import deque
from datetime import datetime, timedelta
import threading
from abc import ABC, abstractmethod
import logging
import json

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Represents the state of the circuit breaker."""
    CLOSED = "CLOSED"           # Normal operation
    OPEN = "OPEN"               # Failing, rejecting requests
    HALF_OPEN = "HALF_OPEN"     # Testing recovery
    DEGRADED = "DEGRADED"       # Elevated latency detected


@dataclass
class LatencyMetrics:
    """Tracks latency statistics."""
    timestamp: float
    duration_ms: float
    
    def __post_init__(self):
        if self.duration_ms < 0:
            raise ValueError("Duration cannot be negative")


@dataclass
class CircuitBreakerConfig:
    """Configuration for the adaptive circuit breaker."""
    # Latency thresholds (in milliseconds)
    initial_latency_threshold: float = 100.0
    max_latency_threshold: float = 5000.0
    min_latency_threshold: float = 10.0
    
    # Error thresholds
    error_rate_threshold: float = 0.5  # 50%
    error_count_threshold: int = 5
    
    # Window sizes
    metrics_window_size: int = 100  # Number of requests to track
    stats_check_interval: float = 5.0  # Seconds
    
    # State transitions
    open_timeout: float = 30.0  # Time before attempting half-open
    half_open_success_threshold: int = 3  # Successes needed to close
    half_open_failure_threshold: int = 1  # Failures to reopen
    half_open_requests_limit: int = 5  # Max requests in half-open
    
    # Adaptive adjustment
    latency_percentile: int = 95  # Use p95 latency
    adjust_threshold_on_recovery: bool = True
    threshold_adjustment_rate: float = 0.1  # 10% adjustment per cycle
    
    # Degradation detection
    degradation_threshold: float = 1.5  # Latency increase multiplier
    degradation_sample_size: int = 20


@dataclass
class CircuitBreakerMetrics:
    """Current metrics and state information."""
    state: CircuitState
    total_requests: int
    failed_requests: int
    error_rate: float
    current_latency_threshold: float
    p50_latency: float
    p95_latency: float
    p99_latency: float
    last_failure_time: Optional[float] = None
    last_success_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    half_open_requests_count: int = 0
    state_change_time: Optional[float] = None
    estimated_recovery_time: Optional[float] = None


class LatencyAnalyzer:
    """Analyzes latency trends and detects degradation."""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.baseline_latency: Optional[float] = None
        self.recent_samples: deque = deque(maxlen=config.degradation_sample_size)
    
    def add_sample(self, duration_ms: float) -> None:
        """Add a latency sample."""
        self.recent_samples.append(duration_ms)
        
        # Initialize baseline from first samples
        if self.baseline_latency is None and len(self.recent_samples) >= 5:
            self.baseline_latency = statistics.median(self.recent_samples)
    
    def is_degrading(self) -> Tuple[bool, Optional[float]]:
        """
        Detect if the service is degrading.
        Returns (is_degrading, degradation_factor)
        """
        if self.baseline_latency is None or len(self.recent_samples) < 5:
            return False, None
        
        current_median = statistics.median(self.recent_samples)
        degradation_factor = current_median / self.baseline_latency
        
        is_degrading = degradation_factor > self.config.degradation_threshold
        
        return is_degrading, degradation_factor if is_degrading else None
    
    def get_percentile_latency(self, percentile: int) -> Optional[float]:
        """Calculate latency percentile from recent samples."""
        if not self.recent_samples:
            return None
        
        sorted_samples = sorted(self.recent_samples)
        index = max(0, int(len(sorted_samples) * (percentile / 100.0)))
        return sorted_samples[index]
    
    def get_latency_stats(self) -> dict:
        """Get current latency statistics."""
        if not self.recent_samples:
            return {}
        
        samples = list(self.recent_samples)
        return {
            "p50": statistics.median(samples),
            "p95": self.get_percentile_latency(95),
            "p99": self.get_percentile_latency(99),
            "mean": statistics.mean(samples),
            "stdev": statistics.stdev(samples) if len(samples) > 1 else 0,
        }


class AdaptiveThresholdAdjuster:
    """Adapts latency thresholds based on observed metrics."""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.current_threshold = config.initial_latency_threshold
        self.adjustment_history: List[Tuple[float, float]] = []
    
    def adjust_threshold(self, analyzer: LatencyAnalyzer, 
                        error_rate: float) -> float:
        """
        Adjust threshold based on current conditions.
        Returns new threshold.
        """
        stats = analyzer.get_latency_stats()
        p95_latency = stats.get("p95", self.current_threshold)
        
        if error_rate > self.config.error_rate_threshold:
            # High error rate: lower threshold to catch issues
            new_threshold = self.current_threshold * (1 - self.config.threshold_adjustment_rate)
        elif error_rate < 0.1 and p95_latency < self.current_threshold * 0.8:
            # Low error rate and good latency: allow higher threshold
            if self.config.adjust_threshold_on_recovery:
                new_threshold = self.current_threshold * (1 + self.config.threshold_adjustment_rate * 0.5)
            else:
                new_threshold = self.current_threshold
        else:
            # Keep current threshold
            new_threshold = self.current_threshold
        
        # Clamp to min/max
        new_threshold = max(
            self.config.min_latency_threshold,
            min(self.config.max_latency_threshold, new_threshold)
        )
        
        if new_threshold != self.current_threshold:
            self.adjustment_history.append((time.time(), new_threshold))
            logger.info(f"Threshold adjusted: {self.current_threshold:.2f}ms → {new_threshold:.2f}ms")
            self.current_threshold = new_threshold
        
        return self.current_threshold


class CircuitBreaker:
    """
    Adaptive circuit breaker for latency-sensitive APIs.
    
    Detects and adapts to:
    - Gradual latency increases
    - Error rate changes
    - Service recovery patterns
    """
    
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        
        # State management
        self._state = CircuitState.CLOSED
        self._state_lock = threading.RLock()
        self._state_change_time = time.time()
        
        # Metrics tracking
        self._metrics_deque: deque = deque(maxlen=self.config.metrics_window_size)
        self._error_count = 0
        self._request_count = 0
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        
        # Half-open state tracking
        self._half_open_requests = 0
        self._half_open_successes = 0
        self._half_open_failures = 0
        
        # Latency analysis
        self.latency_analyzer = LatencyAnalyzer(self.config)
        self.threshold_adjuster = AdaptiveThresholdAdjuster(self.config)
        
        # Background monitoring
        self._last_stats_check = time.time()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitoring_enabled = False
        
        # Event callbacks
        self._on_state_change: List[Callable[[CircuitState, CircuitState], None]] = []
        self._on_degradation_detected: List[Callable[[float], None]] = []
    
    def start_monitoring(self) -> None:
        """Start background monitoring thread."""
        if self._monitoring_enabled:
            return
        
        self._monitoring_enabled = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="CircuitBreakerMonitor"
        )
        self._monitor_thread.start()
        logger.info("Circuit breaker monitoring started")
    
    def stop_monitoring(self) -> None:
        """Stop background monitoring thread."""
        self._monitoring_enabled = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        logger.info("Circuit breaker monitoring stopped")
    
    def _monitor_loop(self) -> None:
        """Background monitoring loop."""
        while self._monitoring_enabled:
            try:
                current_time = time.time()
                if current_time - self._last_stats_check >= self.config.stats_check_interval:
                    self._check_and_update_state()
                    self._last_stats_check = current_time
                
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
    
    def _check_and_update_state(self) -> None:
        """Check metrics and update circuit state."""
        with self._state_lock:
            if not self._metrics_deque:
                return
            
            # Calculate current metrics
            error_rate = self._error_count / max(1, self._request_count)
            
            # Check for degradation
            is_degrading, degradation_factor = self.latency_analyzer.is_degrading()
            
            if is_degrading an

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Adaptive Circuit Breaker for Latency-Degrading APIs

I'll implement a production-grade adaptive circuit breaker that tracks latency trends, automatically adjusts thresholds, and supports graceful recovery.

```python
import time
import threading
from enum import Enum
from collections import deque
from dataclasses import dataclass
from typing import Callable, Optional, Deque, Any, Dict
import statistics


class State(Enum):
    """Circuit breaker state machine."""
    CLOSED = "closed"           # healthy, normal operation
    OPEN = "open"               # tripped, fast-failing
    HALF_OPEN = "half_open"     # probing for recovery


class CircuitOpenError(Exception):
    """Raised when circuit breaker rejects a call."""
    pass


@dataclass
class BreakerConfig:
    """Configuration for adaptive circuit breaker behavior."""
    
    # --- Exponential Weighted Moving Average (EWMA) parameters ---
    fast_alpha: float = 0.30        # fast signal: reacts quickly to recent latency
    slow_alpha: float = 0.02        # slow signal: adaptive baseline, resists noise
    
    # --- Degradation detection ---
    trip_ratio: float = 2.0         # trip when fast > slow * trip_ratio
    recover_ratio: float = 1.30     # recover when latency < slow * recover_ratio
    consecutive_breaches: int = 5   # sustained degradation samples to trip
    require_rising_trend: bool = True  # confirm upward latency trend before trip
    min_samples: int = 20           # warmup period before stats are trusted
    latency_floor: float = 0.005    # ignore noise below 5ms
    
    # --- Error rate monitoring (supplementary signal) ---
    error_rate_threshold: float = 0.50
    error_window: int = 20
    
    # --- Cooldown / backoff strategy ---
    base_cooldown: float = 5.0      # initial cooldown in seconds
    max_cooldown: float = 120.0     # maximum cooldown cap
    backoff_multiplier: float = 2.0 # exponential backoff factor
    
    # --- Half-open recovery probing ---
    half_open_max_probes: int = 3       # concurrent probes allowed
    half_open_success_threshold: int = 3 # successful probes needed to close
    
    # --- Trend analysis ---
    trend_window: int = 30          # samples for slope estimation


class LatencyStats:
    """Tracks latency with dual exponential moving averages."""
    
    def __init__(self, fast_alpha: float, slow_alpha: float, floor: float):
        self.fast_alpha = fast_alpha
        self.slow_alpha = slow_alpha
        self.floor = floor
        
        self.fast: Optional[float] = None   # recent latency signal
        self.slow: Optional[float] = None   # adaptive baseline
        self.recent: Deque[float] = deque(maxlen=30)
    
    def update(self, latency: float, is_healthy: bool = True) -> None:
        """Update both EWMA signals. Only update slow baseline when healthy."""
        latency = max(latency, self.floor)
        self.recent.append(latency)
        
        # Update fast signal (always reacts)
        self.fast = self._ewma(self.fast, latency, self.fast_alpha)
        
        # Update slow signal only when healthy to prevent creep-up masking degradation
        if is_healthy:
            self.slow = self._ewma(self.slow, latency, self.slow_alpha)
    
    @staticmethod
    def _ewma(prev: Optional[float], value: float, alpha: float) -> float:
        """Exponential weighted moving average."""
        return value if prev is None else alpha * value + (1 - alpha) * prev
    
    def get_ratio(self) -> Optional[float]:
        """Return fast/slow ratio (degradation indicator)."""
        if self.fast is None or self.slow is None:
            return None
        return self.fast / self.slow
    
    def get_trend_slope(self) -> float:
        """Compute normalized slope of recent latencies (scale-independent)."""
        n = len(self.recent)
        if n < 2 or self.slow is None:
            return 0.0
        
        xs = list(range(n))
        ys = list(self.recent)
        mean_x = (n - 1) / 2.0
        mean_y = sum(ys) / n
        
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        denominator = sum((x - mean_x) ** 2 for x in xs)
        
        if denominator == 0 or mean_y == 0:
            return 0.0
        
        # Normalize by mean to make slope scale-independent
        slope = numerator / denominator
        return slope / mean_y
    
    def get_p95(self) -> Optional[float]:
        """Return 95th percentile of recent latencies."""
        if not self.recent:
            return None
        return statistics.quantiles(self.recent, n=20)[18] if len(self.recent) > 1 else None


class AdaptiveCircuitBreaker:
    """
    Adaptive circuit breaker that responds to latency degradation.
    
    Key features:
    - Tracks latency with dual EWMAs (fast reaction + slow baseline)
    - Detects sustained degradation trends, not just spikes
    - Automatically adjusts threshold based on API's healthy baseline
    - Exponential backoff for reopening
    - Half-open state with limited probing for recovery verification
    - Thread-safe with full state exposure
    """
    
    def __init__(self, config: Optional[BreakerConfig] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = config or BreakerConfig()
        self._clock = clock
        self._lock = threading.RLock()
        
        # State machine
        self._state = State.CLOSED
        
        # Latency tracking
        self._latency = LatencyStats(
            self.cfg.fast_alpha,
            self.cfg.slow_alpha,
            self.cfg.latency_floor
        )
        
        # Error tracking
        self._errors: Deque[bool] = deque(maxlen=self.cfg.error_window)
        
        # Breach tracking (consecutive degradation detections)
        self._consecutive_breaches = 0
        self._total_requests = 0
        
        # Open/backoff state
        self._trip_count = 0
        self._open_until = 0.0
        
        # Half-open probing state
        self._probes_in_flight = 0
        self._probe_successes = 0
    
    # ============================================================ Public API
    
    @property
    def state(self) -> State:
        """Get current circuit breaker state."""
        with self._lock:
            self._attempt_recovery()
            return self._state
    
    def snapshot(self) -> Dict[str, Any]:
        """
        Expose comprehensive breaker state for metrics/dashboards.
        
        Returns:
            Dict with state, latency signals, thresholds, health metrics
        """
        with self._lock:
            self._attempt_recovery()
            
            fast = self._latency.fast
            slow = self._latency.slow
            ratio = self._latency.get_ratio()
            trip_threshold = slow * self.cfg.trip_ratio if slow else None
            
            return {
                "state": self._state.value,
                "fast_latency_ms": fast * 1000 if fast else None,
                "baseline_latency_ms": slow * 1000 if slow else None,
                "p95_latency_ms": (self._latency.get_p95() * 1000 
                                   if self._latency.get_p95() else None),
                "trip_threshold_ms": trip_threshold * 1000 if trip_threshold else None,
                "latency_ratio": ratio,
                "trend_slope": self._latency.get_trend_slope(),
                "is_trending_up": self._latency.get_trend_slope() > 0,
                "error_rate": self._error_rate(),
                "consecutive_breaches": self._consecutive_breaches,
                "trip_count": self._trip_count,
                "total_requests": self._total_requests,
                "cooldown_remaining_sec": max(0.0, self._open_until - self._clock()),
                "samples_in_window": len(self._latency.recent),
                "warmup_complete": self._total_requests >= self.cfg.min_samples,
                "half_open_probes_in_flight": self._probes_in_flight,
                "half_open_successes": self._probe_successes,
            }
    
    def call(self, fn: Callable, *args, **kwargs) -> Any:
        """
        Execute function under circuit breaker protection.
        
        Args:
            fn: Callable to execute
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Result of fn
            
        Raises:
            CircuitOpenError: If breaker is open
        """
        is_probe = self._before_call()
        start_time = self._clock()
        
        try:
            result = fn(*args, **kwargs)
            self._after_call(
                latency=self._clock() - start_time,
                success=True,
                is_probe=is_probe
            )
            return result
        except Exception as e:
            self._after_call(
                latency=self._clock() - start_time,
                success=False,
                is_probe=is_probe
            )
            raise
    
    async def call_async(self, fn: Callable, *args, **kwargs) -> Any:
        """Async version of call() for coroutines."""
        is_probe = self._before_call()
        start_time = self._clock()
        
        try:
            result = await fn(*args, **kwargs)
            self._after_call(
                latency=self._clock() - start_time,
                success=True,
                is_probe=is_probe
            )
            return result
        except Exception:
            self._after_call(
                latency=self._clock() - start_time,
                success=False,
                is_probe=is_probe
            )
            raise
    
    # ========================================================= Internal Logic
    
    def _before_call(self) -> bool:
        """
        Check if call is allowed. Transition OPEN → HALF_OPEN if ready.
        
        Returns:
            True if this is a half-open probe, False for normal calls
            
        Raises:
            CircuitOpenError: If circuit is open
        """
        with self._lock:
            self._attempt_recovery()
            
            if self._state == State.OPEN:
                raise CircuitOpenError("circuit breaker is open; failing fast")

---

<details><summary>Reasoning trace supplied to Haiku</summary>

I need to build an adaptive circuit breaker that tracks latency patterns and automatically adjusts its thresholds, with support for half-open recovery and state exposure. I'll implement this in Python to keep it clear and accessible.

I'm designing a rolling latency window to compute percentiles and exponential weighted moving averages, then deriving an adaptive threshold from a long-term baseline of healthy latency. The core logic detects when recent latency trends significantly exceed this baseline—using either linear regression or comparing short-term versus long-term EWMA—to decide when to trip the breaker. The state machine cycles through CLOSED (normal operation, updating baseline), OPEN (fast-fail after cooldown), and HALF_OPEN (allowing probe requests to verify recovery), with the half-open phase checking if latency returns to healthy levels before closing again.

I'll make it thread-safe with locking and structure it around a `LatencyStats` class that tracks fast and slow EWMA signals plus variance, feeding into an `AdaptiveCircuitBreaker` class. The key insight is using the ratio of fast EWMA to slow EWMA as a degradation score—when latency spikes, the fast signal rises above the slow baseline, and I'll only update the slow baseline during healthy periods to prevent it from creeping upward and masking degradation. I'll also add an absolute floor to avoid false positives on tiny latencies and require consecutive breaches to confirm sustained degradation rather than reacting to single spikes.

Writing the implementation... Defining the circuit breaker class... Writing the circuit breaker logic...

**Conclusion:** Here's a production-minded implementation in Python. The core idea: track latency with two exponentially-weighted moving averages (a **fast** signal for "right now" and a **slow** signal that acts as a self-adjusting **baseline**), then trip on a *sustained rising trend* relative to that baseline — not on raw error counts alone.

```python
import time
import threading
from enum import Enum
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional, Deque


class State(Enum):
    CLOSED = "closed"       # healthy, traffic flows
    OPEN = "open"           # tripped, fail fast
    HALF_OPEN = "half_open" # probing recovery


class CircuitOpenError(Exception):
    """Raised when the breaker rejects a call."""


@dataclass
class BreakerConfig:
    # --- EWMA smoothing ---
    fast_alpha: float = 0.30      # reacts quickly to recent latency
    slow_alpha: float = 0.02      # slow-moving adaptive baseline

    # --- Trend / degradation detection ---
    trip_ratio: float = 2.0       # fast > slow * trip_ratio  => degraded
    recover_ratio: float = 1.30   # latency must fall below slow * this to heal
    consecutive_breaches: int = 5 # sustained degradation before tripping
    require_rising_trend: bool = True  # only trip if latency is trending UP
    min_samples: int = 20         # warmup before we trust the signal
    latency_floor: float = 0.005  # ignore jitter under 5ms

    # --- Error handling (still matters, just not the only signal) ---
    error_rate_threshold: float = 0.5
    error_window: int = 20

    # --- Recovery ---
    base_cooldown: float = 5.0    # seconds before first half-open probe
    max_cooldown: float = 120.0   # cap on exponential backoff
    half_open_max_probes: int = 3         # concurrent probes allowed
    half_open_success_needed: int = 3     # healthy probes to fully close

    trend_window: int = 30        # samples used for slope estimation


class AdaptiveCircuitBreaker:
    def __init__(self, config: Optional[BreakerConfig] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = config or BreakerConfig()
        self._clock = clock
        self._lock = threading.RLock()

        self._state = State.CLOSED

        # latency signals
        self._fast: Optional[float] = None
        self._slow: Optional[float] = None          # adaptive baseline
        self._recent: Deque[float] = deque(maxlen=self.cfg.trend_window)
        self._errors: Deque[bool] = deque(maxlen=self.cfg.error_window)

        self._total = 0
        self._breaches = 0

        # OPEN/backoff state
        self._trip_count = 0
        self._open_until = 0.0

        # HALF_OPEN state
        self._probes_in_flight = 0
        self._probe_successes = 0

    # ---------------------------------------------------------------- public

    @property
    def state(self) -> State:
        with self._lock:
            self._maybe_advance_from_open()
            return self._state

    def snapshot(self) -> dict:
        """Expose current breaker state for dashboards / health checks."""
        with self._lock:
            self._maybe_advance_from_open()
            return {
                "state": self._state.value,
                "fast_latency": self._fast,
                "baseline_latency": self._slow,
                "trip_threshold": (self._slow * self.cfg.trip_ratio
                                   if self._slow else None),
                "latency_ratio": (self._fast / self._slow
                                  if self._fast and self._slow else None),
                "trend_slope": self._slope(),
                "error_rate": self._error_rate(),
                "consecutive_breaches": self._breaches,
                "trip_count": self._trip_count,
                "cooldown_remaining": max(0.0, self._open_until - self._clock()),
                "samples": self._total,
            }

    def call(self, fn: Callable, *args, **kwargs):
        """Execute `fn` under breaker protection."""
        is_probe = self._before()
        start = self._clock()
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._after(self._clock() - start, success=False, is_probe=is_probe)
            raise
        self._after(self._clock() - start, success=True, is_probe=is_probe)
        return result

    # --------------------------------------------------------------- gating

    def _before(self) -> bool:
        """Decide if a call may proceed. Returns True if it's a half-open probe."""
        with self._lock:
            self._maybe_advance_from_open()

            if self._state == State.OPEN:
                raise CircuitOpenError("circuit open; failing fast")

            if self._state == State.HALF_OPEN:
                if self._probes_in_flight >= self.cfg.half_open_max_probes:
                    raise CircuitOpenError("half-open probe limit reached")
                self._probes_in_flight += 1
                return True

            return False  # CLOSED

    def _after(self, latency: float, success: bool, is_probe: bool):
        with self._lock:
            self._total += 1
            self._errors.append(not success)

            latency = max(latency, self.cfg.latency_floor)
            self._recent.append(latency)
            self._fast = self._ewma(self._fast, latency, self.cfg.fast_alpha)
            if self._slow is None:
                self._slow = latency

            if is_probe:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                self._handle_probe(latency, success)
                return

            self._handle_closed(latency, success)

    # ---------------------------------------------------------- state logic

    def _handle_closed(self, latency: float, success: bool):
        degraded = self._is_degraded()

        if degraded:
            self._breaches += 1
            if (self._total >= self.cfg.min_samples
                    and self._breaches >= self.cfg.consecutive_breaches):
                self._trip()
        else:
            self._breaches = 0
            # Only adapt the baseline while healthy, so a slow degradation
            # can't silently "drag" the baseline up and mask itself.
            self._slow = self._ewma(self._slow, latency, self.cfg.slow_alpha)

    def _handle_probe(self, latency: float, success: bool):
        healthy = success and self._slow is not None and \
            latency <= self._slow * self.cfg.recover_ratio

        if healthy:
            self._probe_successes += 1
            # let baseline gently re-learn during recovery
            self._slow = self._ewma(self._slow, latency, self.cfg.slow_alpha)
            if self._probe_successes >= self.cfg.half_open_success_needed:
                self._close()
        else:
            # still sick -> reopen with longer backoff
            self._trip()

    def _is_degraded(self) -> bool:
        if self._fast is None or self._slow is None:
            return False

        ratio_bad = self._fast > self._slow * self.cfg.trip_ratio
        errors_bad = self._error_rate() >= self.cfg.error_rate_threshold

        if self.cfg.require_rising_trend and ratio_bad:
            # confirm it's a *trend*, not a single spike
            ratio_bad = self._slope() > 0

        return ratio_bad or errors_bad

    # ------------------------------------------------------------ transitions

    def _trip(self):
        self._state = State.OPEN
        cooldown = min(
            self.cfg.base_cooldown * (2 ** self._trip_count),
            self.cfg.max_cooldown,
        )
        self._trip_count += 1
        self._open_until = self._clock() + cooldown
        self._breaches = 0
        self._probes_in_flight = 0
        self._probe_successes = 0

    def _maybe_advance_from_open(self):
        if self._state == State.OPEN and self._clock() >= self._open_until:
            self._state = State.HALF_OPEN
            self._probes_in_flight = 0
            self._probe_successes = 0

    def _close(self):
        self._state = State.CLOSED
        self._trip_count = 0
        self._breaches = 0
        self._probes_in_flight = 0
        self._probe_successes = 0
        # reset fast signal to baseline to avoid immediate re-trip on stale data
        self._fast = self._slow

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _ewma(prev: Optional[float], value: float, alpha: float) -> float:
        return value if prev is None else alpha * value + (1 - alpha) * prev

    def _error_rate(self) -> float:
        if not self._errors:
            return 0.0
        return sum(self._errors) / len(self._errors)

    def _slope(self) -> float:
        """Normalized least-squares slope of recent latencies (per sample)."""
        n = len(self._recent)
        if n < 2:
            return 0.0
        xs = range(n)
        mean_x = (n - 1) / 2
        mean_y = sum(self._recent) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, self._recent))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0 or mean_y == 0:
            return 0.0
        return (num / den) / mean_y  # normalized so it's scale-independent
```

### Example usage

```python
breaker = AdaptiveCircuitBreaker()

def fetch_from_api():
    ...  # your real HTTP call

try:
    data = breaker.call(fetch_from_api)
except CircuitOpenError:
    data = serve_from_cache()   # graceful degradation

# Health/metrics endpoint
print(breaker.snapshot())
# {'state': 'closed', 'baseline_latency': 0.08,
#  'trip_threshold': 0.16, 'latency_ratio': 1.05, 'trend_slope': 0.002, ...}
```

### How each requirement is met

**Reacts to latency trends, not just errors**
Two EWMAs are maintained: `fast` (recent) and `slow` (baseline). Degradation is detected when `fast > slow * trip_ratio`. With `require_rising_trend=True`, it additionally confirms the normalized regression **slope** over the recent window is positive — so a single latency spike won't trip it, but a genuine creeping slowdown will. Error rate is still a signal (`error_rate_threshold`), just not the only one.

**Automatically adjusts thresholds over time**
The `slow` EWMA is the adaptive baseline, and the effective trip threshold is `slow * trip_ratio`, so it tracks the API's genuine normal behavior. Crucially, the baseline is **only updated while healthy** — otherwise a slow degradation would drag the baseline up and hide itself. Cooldown also adapts via exponential backoff (`base_cooldown * 2^trip_count`, capped at `max_cooldown`).

**Half-open recovery**
After the cooldown expires, `state` lazily transitions `OPEN → HALF_OPEN`. A limited number of concurrent probes (`half_open_max_probes`) are allowed through; the rest still fail fast. A probe counts as healthy only if it succeeds *and* its latency is within `slow * recover_ratio`. After enough healthy probes it fully closes; any bad probe reopens with a longer backoff.

**Exposes current state**
`.state` returns the live `State` enum, and `.snapshot()` returns a full metrics dict (baseline, current latency, computed threshold, ratio, trend slope, error rate, breach count, remaining cooldown) suitable for logging, dashboards, or a `/health` endpoint.

### Notes for real deployment
- The `clock` is injectable — pass a fake clock in tests to simulate cooldowns deterministically.
- It's thread-safe via `RLock`. For asyncio, mirror the `_before`/`_after` structure in an `async call`.
- Tune `fast_alpha`/`slow_alpha` to your traffic rate; if request volume is very bursty, consider a **time-decayed** EWMA instead of count-based so the baseline doesn't go stale during quiet periods.
</details>
