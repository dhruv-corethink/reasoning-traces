# Streaming Join Engine

**Category:** Python / systems coding · `python_06_streaming_join_engine`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **1** |
| Claude Haiku 4.5 + `/reason` | **3** |
| Delta | **+2** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A implements the core event-time join logic with watermarking, deduplication, late-drop, and buffering, but the code is incomplete (truncated eviction and missing sweep) so it cannot run and risks memory leaks and a dedup bug across streams. Candidate B is mostly scaffolding (state store and watermark tracker) and is also syntactically incomplete, lacking the actual ingest/join pipeline, so it satisfies fewer of the stated requirements.

---

## Task
Build a streaming join engine in Python. Two event streams arrive asynchronously and must be joined by key within a time window. Handle out-of-order events, duplicate events, and late arrivals, and prevent unbounded memory growth by safely evicting old state.

---

## WITHOUT — Claude Haiku 4.5 alone
# Streaming Join Engine in Python

I'll build a production-ready streaming join engine with comprehensive handling of edge cases.

```python
import heapq
import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class JoinType(Enum):
    """Join types supported by the engine."""
    INNER = "inner"
    LEFT = "left"
    RIGHT = "right"
    FULL = "full"


class WatermarkStrategy(Enum):
    """Strategy for tracking watermarks (progress through event time)."""
    NONE = "none"
    MONOTONIC = "monotonic"
    BOUNDED_OUT_OF_ORDER = "bounded_out_of_order"


@dataclass
class Event:
    """Represents a streaming event."""
    key: str
    stream_id: int  # 0 or 1 for the two streams
    timestamp: int  # Event time in milliseconds
    data: Dict[str, Any]
    sequence_id: int  # For deduplication
    
    def __repr__(self) -> str:
        return f"Event(key={self.key}, stream={self.stream_id}, ts={self.timestamp}, seq={self.sequence_id})"


@dataclass
class JoinResult:
    """Represents a joined event."""
    key: str
    timestamp: int
    event_left: Optional[Event]
    event_right: Optional[Event]
    result_data: Dict[str, Any]
    join_type: JoinType
    
    def __repr__(self) -> str:
        return (f"JoinResult(key={self.key}, ts={self.timestamp}, "
                f"left={self.event_left is not None}, "
                f"right={self.event_right is not None})")


@dataclass
class WindowState:
    """Stores state for a time window."""
    window_start: int
    window_end: int
    events_left: List[Event] = field(default_factory=list)
    events_right: List[Event] = field(default_factory=list)
    joined_keys: Set[str] = field(default_factory=set)
    
    def is_expired(self, current_watermark: int) -> bool:
        """Check if this window has passed the watermark."""
        return current_watermark > self.window_end
    
    def contains(self, timestamp: int) -> bool:
        """Check if timestamp falls within this window."""
        return self.window_start <= timestamp < self.window_end


@dataclass
class StateMetrics:
    """Metrics for monitoring state health."""
    total_windows: int = 0
    total_events_buffered: int = 0
    duplicate_events_skipped: int = 0
    late_events_received: int = 0
    events_evicted: int = 0
    joins_produced: int = 0
    memory_bytes: int = 0


class JoinStateStore:
    """Thread-safe state store for managing window state."""
    
    def __init__(self, 
                 max_windows: int = 1000,
                 max_events_per_window: int = 10000):
        self.max_windows = max_windows
        self.max_events_per_window = max_events_per_window
        
        # Window management
        self.windows: Dict[Tuple[int, int], WindowState] = {}
        self.window_keys = []  # For LRU eviction
        
        # Deduplication
        self.seen_events: Dict[Tuple[int, int, int], bool] = {}  # (stream_id, key, sequence_id) -> True
        self.max_sequence_memory = 100000
        
        # Thread safety
        self.lock = threading.RLock()
        
        # Metrics
        self.metrics = StateMetrics()
    
    def get_or_create_window(self, window_start: int, window_end: int) -> WindowState:
        """Get or create a window."""
        with self.lock:
            key = (window_start, window_end)
            
            if key not in self.windows:
                if len(self.windows) >= self.max_windows:
                    self._evict_oldest_window()
                
                self.windows[key] = WindowState(window_start, window_end)
                self.window_keys.append(key)
                self.metrics.total_windows += 1
            
            return self.windows[key]
    
    def _evict_oldest_window(self):
        """Evict the oldest window when max is reached."""
        if self.window_keys:
            oldest_key = self.window_keys.pop(0)
            old_window = self.windows.pop(oldest_key)
            self.metrics.events_evicted += len(old_window.events_left) + len(old_window.events_right)
            logger.info(f"Evicted window {oldest_key}, freed {self.metrics.events_evicted} events")
    
    def is_duplicate(self, stream_id: int, key: str, sequence_id: int) -> bool:
        """Check if event is a duplicate."""
        with self.lock:
            event_key = (stream_id, key, sequence_id)
            
            # Cleanup old sequence entries if memory is high
            if len(self.seen_events) > self.max_sequence_memory:
                # Keep only recent sequences
                self.seen_events.clear()
            
            if event_key in self.seen_events:
                self.metrics.duplicate_events_skipped += 1
                return True
            
            self.seen_events[event_key] = True
            return False
    
    def add_event(self, event: Event, window: WindowState):
        """Add event to a window."""
        with self.lock:
            if event.stream_id == 0:
                events = window.events_left
            else:
                events = window.events_right
            
            if len(events) < self.max_events_per_window:
                events.append(event)
                self.metrics.total_events_buffered += 1
            else:
                logger.warning(f"Window full for stream {event.stream_id}, dropping event {event}")
    
    def cleanup_expired_windows(self, watermark: int):
        """Remove expired windows."""
        with self.lock:
            expired_keys = [
                key for key, window in self.windows.items()
                if window.is_expired(watermark)
            ]
            
            for key in expired_keys:
                window = self.windows.pop(key)
                self.window_keys.remove(key)
                self.metrics.events_evicted += len(window.events_left) + len(window.events_right)
                logger.debug(f"Cleaned up expired window {key}")
    
    def get_metrics(self) -> StateMetrics:
        """Get current metrics."""
        with self.lock:
            self.metrics.total_events_buffered = sum(
                len(w.events_left) + len(w.events_right) 
                for w in self.windows.values()
            )
            self.metrics.total_windows = len(self.windows)
            return StateMetrics(**vars(self.metrics))


class WatermarkTracker:
    """Tracks watermark (progress through event time)."""
    
    def __init__(self, strategy: WatermarkStrategy, allowed_lateness_ms: int = 60000):
        self.strategy = strategy
        self.allowed_lateness_ms = allowed_lateness_ms
        self.watermarks = [0, 0]  # Per stream
        self.lock = threading.Lock()
    
    def update(self, stream_id: int, timestamp: int):
        """Update watermark for a stream."""
        with self.lock:
            if self.strategy == WatermarkStrategy.MONOTONIC:
                self.watermarks[stream_id] = max(self.watermarks[stream_id], timestamp)
            elif self.strategy == WatermarkStrategy.BOUNDED_OUT_OF_ORDER:
                self.watermarks[stream_id] = max(self.watermarks[stream_id], timestamp - self.allowed_lateness_ms)
    
    def get_global_watermark(self) -> int:
        """Get the minimum watermark across all streams."""
        with self.lock:
            return min(self.watermarks)
    
    def is_late(self, timestamp: int) -> bool:
        """Check if event is late."""
        with self.lock:
            watermark = min(self.watermarks)
            return timestamp < watermark - self.allowed_lateness_ms


class StreamingJoinEngine:
    """Main streaming join engine."""
    
    def __init__(self,
                 window_size_ms: int = 60000,
                 window_slide_ms: Optional[int] = None,
                 join_type: JoinType = JoinType.INNER,
                 join_fn: Optional[Callable[[Event, Event], Dict[str, Any]]] = None,
                 watermark_strategy: WatermarkStrategy = WatermarkStrategy.BOUNDED_OUT_OF_ORDER,
                 allowed_lateness_ms: int = 60000,
                 max_windows: int = 1000):
        """
        Initialize the streaming join engine.
        
        Args:
            window_size_ms: Size of each time window in milliseconds
            window_slide_ms: Sliding step (None = tumbling windows)
            join_type: Type of join (INNER, LEFT, RIGHT, FULL)
            join_fn: Function to join two events
            watermark_strategy: Strategy for watermark advancement
            allowed_lateness_ms: How late an event can be
            max_windows: Maximum number of windows to keep in memory
        """
        self.window_size_ms = window_size_ms
        self.window_slide_ms = window_slide_ms or window_size_ms
        self.join_type = join_type
        self.join_fn = join_fn or self._default_join_fn
        
        self.state_store = JoinStateStore(max_windows=max_windows)
        self.watermark_tracker = WatermarkTracker(watermark_strategy, allowed_lateness_ms)
        
        # Result callbacks
        self.on_result: List[Callable[[JoinResult], None]] = []
        self.on_late_event: List[Callable[[Event], None]] = []
        
        # Thread safety
        self.lock = threading.Lock()
        
        # Metrics
        self.metrics = StateMetrics()
    
    def _default_join_fn(self, left: Event, right: Event) -> Dict[str, Any]:
        """Default join function - merges data from both events."""
        result = {"left": left.data if left else None, "right": right.data if right else None}
        return result
    
    def get

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Streaming Join Engine in Python

I'll build a complete, production-ready streaming join engine handling all the edge cases you mentioned.

```python
from __future__ import annotations

import asyncio
import bisect
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("join_engine")


@dataclass
class Event:
    """An event arriving on one of two streams."""
    stream: str          # "left" or "right"
    key: str             # join key
    timestamp: float     # event time (not wall-clock arrival time)
    value: Any           # payload
    event_id: str        # stable identifier for deduplication


@dataclass
class JoinResult:
    """Result of a successful join."""
    key: str
    left: Event
    right: Event
    lag: float  # |left.ts - right.ts|


class _KeyState:
    """Per-key state: time-sorted buffers + deduplication index."""
    __slots__ = ("buffers", "seen")

    def __init__(self, streams: Tuple[str, str]) -> None:
        # Each buffer: list of (timestamp, sequence, Event), kept sorted by timestamp
        self.buffers: Dict[str, List[Tuple[float, int, Event]]] = {s: [] for s in streams}
        # Dedup index: event_id -> timestamp for both dedup and retention tracking
        self.seen: Dict[str, float] = {}

    def is_empty(self) -> bool:
        """Check if this key state has no buffered events or pending dedup."""
        return not self.seen and all(not b for b in self.buffers.values())


class StreamingJoinEngine:
    """
    Interval join engine for two asynchronous event streams.

    Join condition: events from left and right with the same key join if
    |left.timestamp - right.timestamp| <= window.

    Key features:
    - Event-time semantics with watermark tracking
    - Deduplication by event_id
    - Late-arrival detection and safe dropping
    - Watermark-driven state eviction (bounded memory)
    - Out-of-order event handling via grace period
    - Single-writer concurrency (async/await, no locks)
    """

    def __init__(
        self,
        window: float,
        grace: float = 0.0,
        streams: Tuple[str, str] = ("left", "right"),
        on_result: Optional[Callable[[JoinResult], Awaitable[None]]] = None,
        sweep_interval: int = 1000,
        max_events_per_key: Optional[int] = None,
    ) -> None:
        """
        Args:
            window: time window for joining (must be >= 0)
            grace: grace period for out-of-order events (must be >= 0)
            streams: tuple of two stream names
            on_result: optional async callback fired on each join
            sweep_interval: # of events before triggering global sweep
            max_events_per_key: hard cap per key (for pathological hot keys)
        """
        assert len(streams) == 2, "exactly two streams required"
        assert window >= 0, "window must be >= 0"
        assert grace >= 0, "grace must be >= 0"

        self.window = window
        self.grace = grace
        self.streams = tuple(streams)
        self.on_result = on_result
        self.sweep_interval = sweep_interval
        self.max_events_per_key = max_events_per_key

        # Per-key state keyed by (stream, key)
        self._state: Dict[str, _KeyState] = {}

        # Max timestamp seen per stream (drives watermark)
        self._max_ts: Dict[str, float] = {s: float("-inf") for s in streams}

        # Monotonic sequence counter for deterministic tie-breaking
        self._seq = 0

        # Event inbox (single writer ensures thread-safe mutations)
        self._inbox: asyncio.Queue[Event] = asyncio.Queue()

        # Results queue
        self.results: asyncio.Queue[JoinResult] = asyncio.Queue()

        # Main processing task
        self._task: Optional[asyncio.Task] = None

        # Operation counter (used to trigger periodic sweeps)
        self._ops = 0

        # Metrics for observability
        self.metrics = {
            "processed": 0,        # total events ingested
            "emitted": 0,          # total join results
            "duplicates": 0,       # events dropped as duplicates
            "late_dropped": 0,     # events dropped as provably un-joinable
            "evicted": 0,          # individual event buffers evicted
            "capacity_dropped": 0, # events dropped due to per-key hard cap
        }

    # ====================================================================== public API

    def start(self) -> None:
        """Start the join engine's processing loop."""
        self._task = asyncio.create_task(self._run())

    async def submit(self, event: Event) -> None:
        """Submit an event to one of the streams (non-blocking)."""
        await self._inbox.put(event)

    async def stop(self) -> None:
        """Wait for all submitted events to be processed and shut down."""
        await self._inbox.join()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def watermark(self) -> float:
        """
        Current watermark: min progress across streams minus grace.
        Events below (watermark - window) can never join future events.
        """
        return min(self._max_ts.values()) - self.grace

    def get_state_size(self) -> int:
        """Total number of buffered events across all keys."""
        return sum(
            len(st.buffers["left"]) + len(st.buffers["right"])
            for st in self._state.values()
        )

    # ====================================================================== internals

    def _other(self, stream: str) -> str:
        """Return the name of the opposite stream."""
        a, b = self.streams
        return b if stream == a else a

    async def _run(self) -> None:
        """Main processing loop: drain inbox and process events sequentially."""
        while True:
            event = await self._inbox.get()
            try:
                await self._process(event)
            except Exception:
                logger.exception("error processing event: %r", event)
            finally:
                self._inbox.task_done()

    async def _process(self, event: Event) -> None:
        """
        Core join logic:
        1. Deduplicate
        2. Advance watermark
        3. Check if event is hopelessly late
        4. Probe opposite stream for matches
        5. Buffer this event
        6. Evict old state
        """
        self.metrics["processed"] += 1

        # Get or create key state
        st = self._state.get(event.key)
        if st is None:
            st = self._state[event.key] = _KeyState(self.streams)

        # 1) Deduplication: silently drop if we've seen this event_id before
        if event.event_id in st.seen:
            self.metrics["duplicates"] += 1
            return

        # 2) Advance watermark only forward
        if event.timestamp > self._max_ts[event.stream]:
            self._max_ts[event.stream] = event.timestamp

        # Eviction threshold: anything older cannot possibly join anything new
        # (since new events have ts >= watermark, and must be within window)
        threshold = self.watermark() - self.window

        # 3) Late-arrival guard: if event is before threshold, it would be evicted
        #    immediately and cannot join anything, so drop it
        if event.timestamp < threshold:
            self.metrics["late_dropped"] += 1
            return

        # Record event_id for dedup (with its timestamp for retention)
        st.seen[event.event_id] = event.timestamp

        # 4) Probe opposite stream's buffer for matches within the join window
        other_stream = self._other(event.stream)
        buf = st.buffers[other_stream]

        # Binary search for the range [event.ts - window, event.ts + window]
        lo = bisect.bisect_left(buf, (event.timestamp - self.window,))
        hi = bisect.bisect_right(buf, (event.timestamp + self.window, float("inf")))

        for _, _, other_event in buf[lo:hi]:
            await self._emit(event, other_event)

        # 5) Buffer this event for future opposite-stream events to join
        self._seq += 1
        bisect.insort(st.buffers[event.stream], (event.timestamp, self._seq, event))

        # 6a) Hard per-key cap: if configured, drop oldest events within window if we exceed it
        #     (protects against hot keys)
        if self.max_events_per_key is not None:
            buf = st.buffers[event.stream]
            overflow = len(buf) - self.max_events_per_key
            if overflow > 0:
                dropped_ts = [ev[2].event_id for ev in buf[:overflow]]
                for eid in dropped_ts:
                    st.seen.pop(eid, None)
                del buf[:overflow]
                self.metrics["capacity_dropped"] += overflow

        # 6b) Eager per-key eviction: clean old state immediately
        self._evict_key(st, threshold)
        if st.is_empty():
            self._state.pop(event.key, None)

        # 7) Periodic global sweep to catch stale keys
        self._ops += 1
        if self._ops % self.sweep_interval == 0:
            self._sweep(threshold)

    async def _emit(self, ev_left_or_right: Event, ev_opposite: Event) -> None:
        """Emit a join result, ensuring left/right ordering."""
        left_stream, right_stream = self.streams
        if ev_left_or_right.stream == left_stream:
            left, right = ev_left_or_right, ev_opposite
        else:
            left, right = ev_opposite, ev_left_or_right

        result = JoinResult(
            key=ev_left_or_right.key,
            left=left,
            right=right,
            lag=abs(left.timestamp - right.timestamp),
        )
        self.metrics["emitted"] += 1
        await self.results.put(result)
        if self.on_result:
            await self.on_result(result)

    def _evict_key(self, st: _KeyState, threshold: float) -> None:
        """
        Evict events older than threshold for a specific key.
        Also prune dedup index for retained events only.
        """
        for stream in self.streams:
            buf = st.buffers[stream]
            # Binary search for first event >= threshold
            idx = bisect.bisect_left(buf, (threshold,))
            if idx > 0:
                # Remove everything before idx
                for

---

<details><summary>Reasoning trace supplied to Haiku</summary>

I'm designing a streaming join engine that needs to handle async event streams with joins keyed by matching values within time windows, accounting for out-of-order arrivals, duplicates, and late events while keeping memory bounded through state eviction. The core pieces I need are an event model with deduplication IDs, watermark tracking to understand event-time progress, and windowing logic.

For the join semantics, I'm using an interval join where events from stream A match events from stream B if their timestamps fall within a configurable symmetric window around each other. I'll maintain per-key buffers for each stream sorted by time, track seen event IDs for deduplication, and evict old state based on the combined watermark across both streams. The implementation will use asyncio for concurrent stream ingestion.

Writing the core data structures and join logic... Writing the join engine... Implementing the process method... I'm thinking through the eviction strategy—I'll do per-key eviction on each event access plus a periodic global sweep to catch stale keys, amortizing the cost. For dedup retention, I'll tie seen_ids cleanup to the same watermark threshold so old event IDs don't persist indefinitely. Now I'm moving toward the full implementation with an async feed interface and concurrent input handling, though I need to decide whether to use a lock or serialize everything through a single event loop to keep the shared state mutations safe.

Writing the engine implementation... I'm realizing that duplicates arriving after eviction would also get late-dropped anyway since their timestamp would be behind the threshold, so the dedup logic is consistent. For efficiency, I'll use a sequence counter to make events orderable without comparing them directly, then use binary search to probe the other stream's buffer within the time window rather than iterating through everything.

Adding sequence counter... Writing the complete implementation...

**Conclusion:** Below is a complete, self-contained streaming interval-join engine built on `asyncio`. It handles the four hard problems explicitly:

- **Out-of-order events** → event-time processing with a **watermark** (min of per-stream progress minus a reorder grace).
- **Duplicates** → per-key `seen` set of event IDs, whose retention is tied to eviction.
- **Late arrivals** → dropped only when they fall below the point where a join is provably impossible.
- **Unbounded memory** → **watermark-driven eviction** plus optional hard per-key caps.

---

## Design overview

- **Interval join semantics:** event `a` (left) joins event `b` (right) iff `|a.ts − b.ts| ≤ window`.
- **Single-writer state:** all events funnel through one internal queue, so state is mutated by exactly one task — no locks, no races.
- **Watermark:** `W = min(max_ts_left, max_ts_right) − grace`. It only moves forward.
- **Safe eviction threshold:** `W − window`. Nothing older can ever match a future event (which by definition has `ts ≥ W`), so it is safe to drop.
- **Exactly-once pairs:** each `(a, b)` pair is emitted only when the *second* of the two arrives and probes the other buffer.

```python
from __future__ import annotations

import asyncio
import bisect
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("join_engine")


@dataclass
class Event:
    stream: str          # which stream ("left"/"right")
    key: str             # join key
    timestamp: float     # EVENT time (not arrival time)
    value: Any
    event_id: str        # stable id for deduplication


@dataclass
class JoinResult:
    key: str
    left: Event
    right: Event
    lag: float           # |left.ts - right.ts|


class _KeyState:
    """Per-key buffers (time-sorted) plus a dedup index."""
    __slots__ = ("buffers", "seen")

    def __init__(self, streams: Tuple[str, str]) -> None:
        # each buffer: sorted list of (timestamp, seq, Event)
        self.buffers: Dict[str, List[Tuple[float, int, Event]]] = {s: [] for s in streams}
        self.seen: Dict[str, float] = {}  # event_id -> timestamp (for dedup + eviction)

    def is_empty(self) -> bool:
        return not self.seen and all(not b for b in self.buffers.values())


class StreamingJoinEngine:
    """
    Asynchronous, event-time interval join of two streams.

    join condition: |left.ts - right.ts| <= window   (same key)
    """

    def __init__(
        self,
        window: float,
        grace: float = 0.0,
        streams: Tuple[str, str] = ("left", "right"),
        on_result: Optional[Callable[[JoinResult], Awaitable[None]]] = None,
        sweep_interval: int = 1000,
        max_events_per_key: Optional[int] = None,
    ) -> None:
        assert len(streams) == 2, "exactly two streams supported"
        self.window = window
        self.grace = grace                       # tolerated out-of-orderness
        self.streams = tuple(streams)
        self.on_result = on_result
        self.sweep_interval = sweep_interval     # amortized global eviction cadence
        self.max_events_per_key = max_events_per_key

        self._state: Dict[str, _KeyState] = {}
        self._max_ts: Dict[str, float] = {s: float("-inf") for s in streams}
        self._seq = 0                            # monotonic tiebreaker for sorting

        self._inbox: asyncio.Queue[Event] = asyncio.Queue()
        self.results: asyncio.Queue[JoinResult] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._ops = 0

        self.metrics = {
            "processed": 0, "emitted": 0,
            "duplicates": 0, "late_dropped": 0, "evicted": 0,
            "capacity_dropped": 0,
        }

    # ---------------------------------------------------------------- public API
    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def submit(self, event: Event) -> None:
        await self._inbox.put(event)

    async def stop(self) -> None:
        await self._inbox.join()      # drain everything already submitted
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def watermark(self) -> float:
        return min(self._max_ts.values()) - self.grace

    # ---------------------------------------------------------------- internals
    def _other(self, stream: str) -> str:
        a, b = self.streams
        return b if stream == a else a

    async def _run(self) -> None:
        while True:
            event = await self._inbox.get()
            try:
                await self._process(event)
            except Exception:
                logger.exception("failed processing %r", event)
            finally:
                self._inbox.task_done()

    async def _process(self, event: Event) -> None:
        self.metrics["processed"] += 1
        st = self._state.get(event.key)
        if st is None:
            st = self._state[event.key] = _KeyState(self.streams)

        # 1) Deduplicate. A repeat within retention window is dropped silently.
        if event.event_id in st.seen:
            self.metrics["duplicates"] += 1
            return

        # 2) Advance watermark. Late events (small ts) never move it backward.
        if event.timestamp > self._max_ts[event.stream]:
            self._max_ts[event.stream] = event.timestamp
        threshold = self.watermark() - self.window

        # 3) Late-arrival guard: below threshold, no match is possible and the
        #    event would be evicted immediately, so drop it.
        if event.timestamp < threshold:
            self.metrics["late_dropped"] += 1
            return

        st.seen[event.event_id] = event.timestamp

        # 4) Probe the opposite buffer for matches within the window.
        other = self._other(event.stream)
        buf = st.buffers[other]
        lo = bisect.bisect_left(buf, (event.timestamp - self.window,))
        hi = bisect.bisect_right(buf, (event.timestamp + self.window, float("inf")))
        for _, _, other_ev in buf[lo:hi]:
            await self._emit(event, other_ev)

        # 5) Buffer this event so future opposite-stream events can join it.
        self._seq += 1
        bisect.insort(st.buffers[event.stream], (event.timestamp, self._seq, event))

        # 6) Hard per-key cap (protects against hot keys inside the window).
        if self.max_events_per_key is not None:
            b = st.buffers[event.stream]
            overflow = len(b) - self.max_events_per_key
            if overflow > 0:
                del b[:overflow]  # drop oldest
                self.metrics["capacity_dropped"] += overflow

        # 7) Evict this key eagerly; sweep all keys periodically.
        self._evict_key(st, threshold)
        if st.is_empty():
            self._state.pop(event.key, None)

        self._ops += 1
        if self._ops % self.sweep_interval == 0:
            self._sweep(threshold)

    async def _emit(self, ev: Event, other: Event) -> None:
        a, _ = self.streams
        left, right = (ev, other) if ev.stream == a else (other, ev)
        result = JoinResult(
            key=ev.key, left=left, right=right,
            lag=abs(left.timestamp - right.timestamp),
        )
        self.metrics["emitted"] += 1
        await self.results.put(result)
        if self.on_result:
            await self.on_result(result)

    def _evict_key(self, st: _KeyState, threshold: float) -> None:
        for s in self.streams:
            buf = st.buffers[s]
            idx = bisect.bisect_left(buf, (threshold,))
            if idx:
                del buf[:idx]
                self.metrics["evicted"] += idx
        if st.seen:
            st.seen = {eid: ts for eid, ts in st.seen.items() if ts >= threshold}

    def _sweep(self, threshold: float) -> None:
        for key in list(self._state.keys()):
            st = self._state[key]
            self._evict_key(st, threshold)
            if st.is_empty():
                del self._state[key]
```

---

## Demo

Two producers emit events for shared keys with jitter (out-of-order), occasional duplicates, and one genuinely-late event that gets dropped.

```python
import random


async def demo() -> None:
    logging.basicConfig(level=logging.INFO)

    engine = StreamingJoinEngine(window=5.0, grace=2.0, max_events_per_key=10_000)
    engine.start()

    async def consumer():
        while True:
            r = await engine.results.get()
            print(f"JOIN key={r.key} left.ts={r.left.timestamp} "
                  f"right.ts={r.right.timestamp} lag={r.lag}")
            engine.results.task_done()

    consumer_task = asyncio.create_task(consumer())

    async def producer(stream: str, base_delay: float):
        for i in range(20):
            key = random.choice(["A", "B", "C"])
            # event time with reordering jitter
            ts = float(i) + random.uniform(-1.5, 1.5)
            ev = Event(stream, key, round(ts, 2), f"{stream}-{i}", f"{stream}:{i}")
            await engine.submit(ev)
            # duplicate ~20% of the time
            if random.random() < 0.2:
                await engine.submit(ev)
            await asyncio.sleep(base_delay + random.uniform(0, 0.02))

    await asyncio.gather(producer("left", 0.03), producer("right", 0.035))

    # A hopelessly-late event: watermark has moved far past its timestamp.
    await engine.submit(Event("left", "A", -100.0, "x", "left:late"))

    await engine.stop()
    await asyncio.sleep(0.1)
    consumer_task.cancel()

    print("\nMetrics:", engine.metrics)
    print("Live keys retained:", len(engine._state))


if __name__ == "__main__":
    asyncio.run(demo())
```

---

## Why memory stays bounded

- **State floor:** any event with `ts < W − window` is evicted. Since `W` only rises, buffers only retain a rolling window of recent history per key.
- **Dedup index retention** is tied to the same threshold, so it can't grow without limit either.
- **Empty keys are removed** after eviction, so the key-space also shrinks.
- **`max_events_per_key`** caps pathological hot keys even *inside* the window.

## Correctness notes / trade-offs

- **Exactly-once pairs:** a pair emits when the second event probes the first's buffer; the reverse direction never re-emits because the earlier event only probes what already existed.
- **Late semantics:** an event is dropped only when it's below `W − window`, i.e., provably unable to match any current or future event. Increase `grace` to tolerate more reordering at the cost of more retained state.
- **Watermark stalls:** if one stream goes silent, `W = min(...)` freezes and eviction stalls. In production, add an **idle timeout** that advances a stream's `max_ts` toward wall clock (a common Flink-style pattern) so the watermark keeps moving.
- **Scaling:** for very high key cardinality, replace the periodic full sweep with a global expiry min-heap keyed by timestamp, or shard the engine by `hash(key)` across multiple worker tasks/processes since state is key-partitioned.
</details>
