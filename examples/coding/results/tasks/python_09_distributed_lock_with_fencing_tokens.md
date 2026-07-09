# Distributed Lock with Fencing Tokens

**Category:** Python / systems coding · `python_09_distributed_lock_with_fencing_tokens`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **4** |
| Claude Haiku 4.5 + `/reason` | **9** |
| Delta | **+5** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Candidate A implements atomic acquire/renew/release with unique lock IDs, TTL, and monotonic fencing tokens, and crucially enforces tokens at the resource layer to block stale writers; the code is coherent and runnable. Candidate B permits reentrant acquisition by the same client causing ambiguous ownership, lacks actual enforcement of fencing tokens on writes, and includes a truncated class, making it incomplete and riskier for correctness.

---

## Task
Implement a distributed lock using Redis. Clients may crash or experience network delays while holding locks. Prevent stale lock holders from performing writes using fencing tokens or similar techniques, and ensure lock ownership is unambiguous.

---

## WITHOUT — Claude Haiku 4.5 alone
# Distributed Lock with Redis - Complete Implementation

I'll provide a production-grade distributed lock system that handles crash recovery, network delays, and prevents stale lock holders using fencing tokens.

## 1. Core Lock Implementation

```python
import redis
import uuid
import time
import logging
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from threading import RLock as ThreadLock
import hashlib

logger = logging.getLogger(__name__)


class LockStatus(Enum):
    """Status of lock acquisition"""
    ACQUIRED = "acquired"
    ALREADY_HELD = "already_held"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class FencingToken:
    """Fencing token to prevent stale writes"""
    lock_id: str
    token: int
    timestamp: float
    
    def is_valid_for(self, operation_token: int) -> bool:
        """Check if this token is valid (equal or greater)"""
        return self.token >= operation_token
    
    def __repr__(self) -> str:
        return f"FencingToken(id={self.lock_id}, token={self.token}, ts={self.timestamp})"


class DistributedLock:
    """
    Redis-based distributed lock with fencing tokens.
    
    Prevents stale lock holders from performing writes by:
    1. Generating fencing tokens that increase monotonically
    2. Validating tokens on each write operation
    3. Using Lua scripts for atomic operations
    4. Implementing TTL-based expiration
    """
    
    def __init__(
        self,
        redis_client: redis.Redis,
        lock_name: str,
        timeout: int = 30,
        retry_times: int = 3,
        retry_delay: float = 0.1,
        client_id: Optional[str] = None,
    ):
        """
        Initialize distributed lock.
        
        Args:
            redis_client: Redis client instance
            lock_name: Name of the lock
            timeout: Lock TTL in seconds (for crash recovery)
            retry_times: Number of acquisition attempts
            retry_delay: Delay between retries in seconds
            client_id: Unique client identifier (auto-generated if None)
        """
        self.redis = redis_client
        self.lock_name = lock_name
        self.timeout = timeout
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        
        # Unique identifier for this client
        self.client_id = client_id or str(uuid.uuid4())
        
        # Current lock ownership token
        self.current_token: Optional[FencingToken] = None
        
        # Thread-safe access to token
        self._token_lock = ThreadLock()
        
        # Lua scripts
        self._acquire_script = self.redis.register_script(self._ACQUIRE_SCRIPT)
        self._release_script = self.redis.register_script(self._RELEASE_SCRIPT)
        self._extend_script = self.redis.register_script(self._EXTEND_SCRIPT)
    
    # Lua script for atomic lock acquisition
    _ACQUIRE_SCRIPT = """
    local lock_key = KEYS[1]
    local token_key = KEYS[2]
    local client_id = ARGV[1]
    local timeout = tonumber(ARGV[2])
    
    -- Check if lock is free or owned by us
    local current_owner = redis.call('get', lock_key)
    if current_owner == false or current_owner == client_id then
        -- Increment token for fencing
        local token = redis.call('incr', token_key)
        
        -- Acquire lock with TTL
        redis.call('set', lock_key, client_id, 'EX', timeout)
        
        -- Store lock metadata
        local metadata_key = lock_key .. ':metadata'
        redis.call('hset', metadata_key, 'token', token)
        redis.call('hset', metadata_key, 'timestamp', redis.call('time')[1])
        redis.call('hset', metadata_key, 'client_id', client_id)
        redis.call('expire', metadata_key, timeout)
        
        return {tostring(token), tostring(redis.call('time')[1])}
    end
    
    return {-1, -1}  -- Lock acquisition failed
    """
    
    # Lua script for atomic lock release
    _RELEASE_SCRIPT = """
    local lock_key = KEYS[1]
    local client_id = ARGV[1]
    local expected_token = tonumber(ARGV[2])
    
    local current_owner = redis.call('get', lock_key)
    if current_owner == client_id then
        local metadata_key = lock_key .. ':metadata'
        local current_token = tonumber(redis.call('hget', metadata_key, 'token'))
        
        -- Only release if token matches (prevents stale releases)
        if current_token == expected_token then
            redis.call('del', lock_key)
            redis.call('del', metadata_key)
            return 1
        end
    end
    
    return 0  -- Release failed (not owner or token mismatch)
    """
    
    # Lua script for lock extension (heartbeat)
    _EXTEND_SCRIPT = """
    local lock_key = KEYS[1]
    local client_id = ARGV[1]
    local timeout = tonumber(ARGV[2])
    local expected_token = tonumber(ARGV[3])
    
    local current_owner = redis.call('get', lock_key)
    if current_owner == client_id then
        local metadata_key = lock_key .. ':metadata'
        local current_token = tonumber(redis.call('hget', metadata_key, 'token'))
        
        if current_token == expected_token then
            redis.call('expire', lock_key, timeout)
            redis.call('expire', metadata_key, timeout)
            return 1
        end
    end
    
    return 0  -- Extension failed
    """
    
    def acquire(self, blocking: bool = True) -> Tuple[bool, Optional[FencingToken]]:
        """
        Acquire the distributed lock.
        
        Args:
            blocking: If True, retry until acquired or timeout
            
        Returns:
            Tuple of (success, fencing_token)
        """
        for attempt in range(self.retry_times):
            try:
                result = self._acquire_script(
                    keys=[self.lock_name, f"{self.lock_name}:token_counter"],
                    args=[self.client_id, self.timeout],
                    client=self.redis,
                )
                
                token_val, timestamp = int(result[0]), int(result[1])
                
                if token_val > 0:
                    with self._token_lock:
                        self.current_token = FencingToken(
                            lock_id=self.lock_name,
                            token=token_val,
                            timestamp=float(timestamp),
                        )
                    logger.info(
                        f"Lock acquired: {self.lock_name} "
                        f"(client={self.client_id}, token={token_val})"
                    )
                    return True, self.current_token
                
                if not blocking or attempt == self.retry_times - 1:
                    logger.warning(
                        f"Lock acquisition failed: {self.lock_name} "
                        f"(attempt {attempt + 1}/{self.retry_times})"
                    )
                    return False, None
                
                time.sleep(self.retry_delay)
                
            except redis.RedisError as e:
                logger.error(f"Redis error during lock acquisition: {e}")
                if not blocking:
                    return False, None
                time.sleep(self.retry_delay)
        
        return False, None
    
    def release(self) -> bool:
        """
        Release the distributed lock.
        
        Returns:
            True if released successfully, False otherwise
        """
        if not self.current_token:
            logger.warning(f"No lock held for {self.lock_name}")
            return False
        
        try:
            with self._token_lock:
                token_val = self.current_token.token
            
            result = self._release_script(
                keys=[self.lock_name],
                args=[self.client_id, token_val],
                client=self.redis,
            )
            
            if result:
                with self._token_lock:
                    self.current_token = None
                logger.info(f"Lock released: {self.lock_name} (client={self.client_id})")
                return True
            else:
                logger.warning(
                    f"Lock release failed: {self.lock_name} "
                    f"(token mismatch or not owner)"
                )
                return False
                
        except redis.RedisError as e:
            logger.error(f"Redis error during lock release: {e}")
            return False
    
    def extend(self, additional_timeout: Optional[int] = None) -> bool:
        """
        Extend the lock TTL (heartbeat).
        
        Args:
            additional_timeout: Additional time in seconds (uses default if None)
            
        Returns:
            True if extended successfully, False otherwise
        """
        if not self.current_token:
            logger.warning(f"No lock held for {self.lock_name}")
            return False
        
        timeout = additional_timeout or self.timeout
        
        try:
            with self._token_lock:
                token_val = self.current_token.token
            
            result = self._extend_script(
                keys=[self.lock_name],
                args=[self.client_id, timeout, token_val],
                client=self.redis,
            )
            
            if result:
                logger.debug(
                    f"Lock extended: {self.lock_name} "
                    f"(client={self.client_id}, timeout={timeout}s)"
                )
                return True
            else:
                logger.warning(
                    f"Lock extension failed: {self.lock_name} "
                    f"(lost lock or token mismatch)"
                )
                return False
                
        except redis.RedisError as e:
            logger.error(f"Redis error during lock extension: {e}")
            return False
    
    def get_current_token(self) -> Optional[FencingToken]:
        """Get current fencing token"""
        with self._token_lock:
            return self.current_token
    
    def is_held(self) -> bool:
        """Check if lock is currently held"""
        with self._token_lock:
            return self.current_token is not None
    
    def __enter__(self):
        """Context manager entry"""
        success, token = self.acquire()
        if not success:
            raise RuntimeError(f"Failed to acquire lock: {self.lock_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.release()
        return False


class LockWithHeart

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Distributed Lock with Redis and Fencing Tokens

I'll provide a production-ready implementation that prevents stale lock holders from writing using monotonic fencing tokens.

## Core Implementation

```python
import redis
import uuid
import time
import threading
from typing import Optional, Any, Callable
from dataclasses import dataclass
from contextlib import contextmanager


@dataclass
class LockToken:
    """Represents a valid lock acquisition with a fencing token."""
    lock_id: str
    fence_token: int
    acquired_at: float

    def __repr__(self):
        return f"LockToken(id={self.lock_id[:8]}..., fence={self.fence_token})"


class StaleTokenError(Exception):
    """Raised when a write is attempted with an outdated fencing token."""
    pass


class LockTimeoutError(Exception):
    """Raised when lock acquisition times out."""
    pass


class FencedRedisLock:
    """
    A distributed lock using Redis with monotonic fencing tokens.
    
    Prevents stale lock holders from performing writes by issuing
    strictly-increasing tokens that the protected resource must validate.
    """

    # Atomic acquire: SET lock NX + INCR fence counter
    _ACQUIRE_SCRIPT = """
    if redis.call("set", KEYS[1], ARGV[1], "NX", "PX", ARGV[2]) then
        local token = redis.call("incr", KEYS[2])
        return {1, token}
    else
        return {0, nil}
    end
    """

    # Atomic release: DEL only if we still own it
    _RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    # Atomic renew: PEXPIRE only if we still own it
    _RENEW_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("pexpire", KEYS[1], ARGV[2])
    else
        return 0
    end
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        resource_name: str,
        ttl_ms: int = 10000,
    ):
        """
        Initialize a fenced lock.
        
        Args:
            redis_client: Connected Redis client
            resource_name: Name of the protected resource
            ttl_ms: Lock time-to-live in milliseconds
        """
        self.client = redis_client
        self.resource_name = resource_name
        self.ttl_ms = ttl_ms

        # Keys for lock state and fence counter (monotonic)
        self.lock_key = f"lock:{resource_name}"
        self.fence_key = f"lock:{resource_name}:fence"

        # Register Lua scripts
        self._acquire_script = redis_client.register_script(self._ACQUIRE_SCRIPT)
        self._release_script = redis_client.register_script(self._RELEASE_SCRIPT)
        self._renew_script = redis_client.register_script(self._RENEW_SCRIPT)

        # Current lock state
        self._lock_id: Optional[str] = None
        self._fence_token: Optional[int] = None
        self._acquired_at: Optional[float] = None

    def acquire(
        self,
        timeout_sec: float = 5.0,
        retry_interval_ms: int = 100,
    ) -> LockToken:
        """
        Acquire the lock, returning a fencing token.
        
        Args:
            timeout_sec: Maximum time to wait for lock
            retry_interval_ms: Interval between acquisition attempts
            
        Returns:
            LockToken with fence_token for use in protected writes
            
        Raises:
            LockTimeoutError: If lock not acquired within timeout
        """
        deadline = time.monotonic() + timeout_sec
        lock_id = str(uuid.uuid4())
        retry_interval = retry_interval_ms / 1000.0

        while time.monotonic() < deadline:
            result = self._acquire_script(
                keys=[self.lock_key, self.fence_key],
                args=[lock_id, self.ttl_ms],
            )

            if result and result[0] == 1:
                fence_token = int(result[1])
                self._lock_id = lock_id
                self._fence_token = fence_token
                self._acquired_at = time.monotonic()
                
                return LockToken(
                    lock_id=lock_id,
                    fence_token=fence_token,
                    acquired_at=self._acquired_at,
                )

            time.sleep(retry_interval)

        raise LockTimeoutError(
            f"Could not acquire lock for '{self.resource_name}' within {timeout_sec}s"
        )

    def renew(self) -> bool:
        """
        Extend the lock lease if still held.
        Call from a watchdog thread during long operations.
        
        Returns:
            True if renewal successful, False if lock was lost
        """
        if self._lock_id is None:
            return False

        result = self._renew_script(
            keys=[self.lock_key],
            args=[self._lock_id, self.ttl_ms],
        )
        return result == 1

    def release(self) -> bool:
        """
        Release the lock only if we still own it.
        Never releases a lock acquired by another holder.
        
        Returns:
            True if released, False if we didn't own it
        """
        if self._lock_id is None:
            return False

        result = self._release_script(keys=[self.lock_key], args=[self._lock_id])
        if result == 1:
            self._lock_id = None
            self._fence_token = None
            self._acquired_at = None
            return True
        return False

    def is_held(self) -> bool:
        """Check if this lock instance still holds the lock."""
        if self._lock_id is None:
            return False
        current = self.client.get(self.lock_key)
        return current == self._lock_id.encode()

    def get_token(self) -> Optional[int]:
        """Get the current fencing token (if held)."""
        return self._fence_token

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


class LockWatchdog:
    """
    Background thread that renews a lock periodically.
    Prevents premature expiry during long operations.
    """

    def __init__(self, lock: FencedRedisLock, renew_interval_ms: int = 3000):
        """
        Args:
            lock: The lock to renew
            renew_interval_ms: How often to attempt renewal (~1/3 of TTL)
        """
        self.lock = lock
        self.renew_interval = renew_interval_ms / 1000.0
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock_lost_callback: Optional[Callable] = None

    def set_lock_lost_callback(self, callback: Callable):
        """Set callback to invoke if lock is lost during watchdog tenure."""
        self._lock_lost_callback = callback

    def start(self):
        """Start the watchdog thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        """Watchdog main loop."""
        while not self._stop_event.wait(self.renew_interval):
            if not self.lock.renew():
                # Lock was lost — invoke callback and stop trying
                if self._lock_lost_callback:
                    try:
                        self._lock_lost_callback()
                    except Exception:
                        pass
                break

    def stop(self):
        """Stop the watchdog."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class FencedResource:
    """
    A protected resource that enforces fencing token validation.
    
    Rejects writes from stale lock holders by tracking the highest
    fence token ever committed. This is the defense against GC pauses,
    network delays, and other anomalies that could cause a lock holder
    to lose its lock unnoticed.
    """

    def __init__(self, storage: Any):
        """
        Args:
            storage: Backend storage (e.g., database connection, file handle).
                     Must support atomic conditional writes.
        """
        self.storage = storage
        self._max_token_seen = 0
        self._lock = threading.Lock()

    def write(self, data: Any, token: int) -> Any:
        """
        Write data with fencing token validation.
        
        Args:
            data: Data to write
            token: Fencing token from lock acquisition
            
        Returns:
            Result from storage backend
            
        Raises:
            StaleTokenError: If token is not monotonically increasing
        """
        with self._lock:
            if token <= self._max_token_seen:
                raise StaleTokenError(
                    f"Stale token {token}: already committed writes with "
                    f"token {self._max_token_seen}. A newer lock holder exists."
                )
            
            # Commit both token and data atomically
            result = self.storage.commit(data, token)
            self._max_token_seen = token
            return result

    def get_max_token(self) -> int:
        """Get the highest fencing token committed so far."""
        with self._lock:
            return self._max_token_seen


class InMemoryStorage:
    """Simple in-memory storage backend for demonstration."""

    def __init__(self):
        self.data = None
        self.last_token = 0
        self._lock = threading.Lock()

    def commit(self, data: Any, token: int) -> bool:
        """Atomically store data with token."""
        with self._lock:
            if token <= self.last_token:
                return False
            self.data = data
            self.last_token = token
            return True

    def read(self) -> tuple[Any, int]:
        """Read current data and its token."""
        with self._lock:
            return self.data, self.last_token


```

## Usage Examples

```python
def example_basic_lock():
    """Basic lock acquisition and release."""
    redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    
    lock = FencedRedisLock(redis_client, "orders", ttl_ms=10000)
    try:
        token = lock.acquire(timeout_sec=5.0)

---

<details><summary>Reasoning trace supplied to Haiku</summary>

(no separate trace returned)

**Conclusion:** # Distributed Lock with Redis and Fencing Tokens

## The Core Problem

A naive Redis lock (`SET key value NX PX ttl`) is **not sufficient** because:

1. A client acquires the lock, then experiences a GC pause or network delay
2. The lock expires (TTL), another client acquires it
3. The first client "wakes up" and performs a write, unaware it lost the lock

**TTL alone cannot prevent this** — you need a way for the *protected resource* to reject stale writers. This is what **fencing tokens** solve.

---

## Architecture Overview

```
┌──────────┐  1. acquire()   ┌─────────┐
│ Client A │────────────────▶│  Redis  │
│          │◀────token=33────│         │
└────┬─────┘                 └─────────┘
     │ 2. write(data, token=33)
     ▼
┌──────────────────────────────┐
│  Protected Resource / Storage │
│  (rejects tokens < last seen) │
└──────────────────────────────┘
```

---

## Part 1: The Redis Lock with Monotonic Fencing Tokens

```python
import redis
import uuid
import time
from typing import Optional


class FencedRedisLock:
    """
    A distributed lock backed by Redis that issues monotonically
    increasing fencing tokens to prevent stale-holder writes.
    """

    # Lua: atomically release ONLY if we still own the lock.
    # Prevents releasing a lock that a later client acquired.
    _RELEASE_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """

    # Lua: acquire lock (NX) AND atomically bump a monotonic counter
    # to produce a fencing token. Both operations succeed together.
    _ACQUIRE_SCRIPT = """
    if redis.call("set", KEYS[1], ARGV[1], "NX", "PX", ARGV[2]) then
        local token = redis.call("incr", KEYS[2])
        return token
    else
        return nil
    end
    """

    # Lua: extend the TTL only if we still own the lock (for renewal).
    _EXTEND_SCRIPT = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("pexpire", KEYS[1], ARGV[2])
    else
        return 0
    end
    """

    def __init__(self, client: redis.Redis, resource: str, ttl_ms: int = 10000):
        self.client = client
        self.lock_key = f"lock:{resource}"
        self.token_key = f"lock:{resource}:fence"  # monotonic counter
        self.ttl_ms = ttl_ms
        self.owner_id: Optional[str] = None
        self.token: Optional[int] = None

        self._acquire = client.register_script(self._ACQUIRE_SCRIPT)
        self._release = client.register_script(self._RELEASE_SCRIPT)
        self._extend = client.register_script(self._EXTEND_SCRIPT)

    def acquire(self, timeout_ms: int = 5000, retry_ms: int = 100) -> Optional[int]:
        """
        Attempt to acquire the lock. Returns a fencing token on success,
        None on timeout. The token strictly increases across all holders.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        # Unique owner id so only WE can release/renew our lock instance.
        owner_id = str(uuid.uuid4())

        while time.monotonic() < deadline:
            token = self._acquire(
                keys=[self.lock_key, self.token_key],
                args=[owner_id, self.ttl_ms],
            )
            if token is not None:
                self.owner_id = owner_id
                self.token = int(token)
                return self.token
            time.sleep(retry_ms / 1000)

        return None

    def renew(self) -> bool:
        """Extend the lease if we still hold it. Call from a watchdog."""
        if self.owner_id is None:
            return False
        result = self._extend(
            keys=[self.lock_key],
            args=[self.owner_id, self.ttl_ms],
        )
        return result == 1

    def release(self) -> bool:
        """Release only if we still own it (never steal from a newer holder)."""
        if self.owner_id is None:
            return False
        result = self._release(keys=[self.lock_key], args=[self.owner_id])
        self.owner_id = None
        self.token = None
        return result == 1

    def __enter__(self):
        if self.acquire() is None:
            raise TimeoutError("Could not acquire lock")
        return self

    def __exit__(self, *exc):
        self.release()
```

### Key design points

| Mechanism | Purpose |
|-----------|---------|
| `SET NX PX` | Mutual exclusion + auto-expiry so a crashed client's lock is eventually freed |
| Random `owner_id` | Ensures release/renew only affects *our* lock — unambiguous ownership |
| `INCR` fence counter | Produces a **monotonically increasing** token, atomically with acquisition |
| Lua scripts | Guarantee check-and-act atomicity (no race between GET and DEL) |

---

## Part 2: The Fencing Enforcement (the part that actually saves you)

The lock alone is *advisory*. The **resource must reject stale tokens.**

```python
class FencedResource:
    """
    A protected resource that only accepts writes carrying a fencing
    token >= the highest token it has ever seen. This rejects stale
    lock holders even if Redis wrongly believes they released.
    """

    def __init__(self, storage):
        self.storage = storage          # e.g., a DB or file store
        self._max_token_seen = 0        # persisted alongside data ideally

    def write(self, data, token: int):
        # Reject any token not strictly greater than what we've committed.
        if token <= self._max_token_seen:
            raise StaleTokenError(
                f"Rejected write: token {token} <= last seen "
                f"{self._max_token_seen}. A newer lock holder exists."
            )
        # Commit token + data ATOMICALLY (must be one transaction in real DB).
        self._max_token_seen = token
        self.storage.commit(data)


class StaleTokenError(Exception):
    pass
```

### Why this defeats the GC-pause race

```
Client A: acquire() -> token 33
Client A: <long GC pause / network partition>
   Lock A expires in Redis
Client B: acquire() -> token 34
Client B: write(x, token=34)   # resource now max_token_seen = 34
Client A: wakes up, write(y, token=33)
   -> REJECTED (33 <= 34) ✓  A's stale write is blocked
```

The fencing token converts a *time-based, best-effort* lock into a *correctness-preserving* one.

---

## Part 3: Auto-Renewal Watchdog (avoid premature expiry)

For long operations, run a background thread that renews the lease so the lock doesn't expire *while legitimately in use*:

```python
import threading


class LockWatchdog:
    def __init__(self, lock: FencedRedisLock, interval_ms: int):
        self.lock = lock
        self.interval = interval_ms / 1000
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            if not self.lock.renew():
                # We lost ownership — stop trying and signal the app.
                break

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()
```

> **Renew at ~1/3 of TTL.** With `ttl_ms=10000`, renew every ~3000ms so brief hiccups don't cause loss.

---

## Part 4: Putting It Together

```python
def do_critical_work(client, resource, storage):
    lock = FencedRedisLock(client, "orders", ttl_ms=10000)
    token = lock.acquire(timeout_ms=5000)
    if token is None:
        raise RuntimeError("Lock unavailable")

    watchdog = LockWatchdog(lock, interval_ms=3000)
    watchdog.start()
    try:
        # ALWAYS pass the token to the resource; never trust the lock alone.
        storage.write({"status": "processed"}, token=token)
    except StaleTokenError:
        # We were fenced out — a newer holder exists. Abort safely.
        raise
    finally:
        watchdog.stop()
        lock.release()
```

---

## Important Caveats & Honest Limitations

1. **Single Redis node = single point of failure.** If it dies, all locks vanish.

2. **Redlock (multi-node) is controversial.** Martin Kleppmann's critique shows Redlock is *not* safe under clock jumps / long pauses without fencing. **Fencing tokens are what actually provide safety** — with them, even a simpler single-master Redis lock is acceptable for correctness (though not availability).

3. **The fencing check must be atomic with the write** in the real storage system. If your DB can't do a conditional update (`WHERE incoming_token > stored_token`), you don't have true fencing:
   ```sql
   UPDATE resource
   SET data = :data, fence_token = :token
   WHERE id = :id AND fence_token < :token;
   -- If 0 rows affected -> stale token, reject.
   ```

4. **Fencing tokens are only useful if the resource enforces them.** A lock without a fencing-aware resource is merely advisory and *cannot* prevent stale writes.

5. **Redis failover can lose the INCR counter** (async replication). For strict monotonicity across failovers, persist the counter with AOF `fsync=always`, or source tokens from a strongly-consistent store (e.g., ZooKeeper `zxid`, etcd revision, or a DB sequence).

---

## Summary

| Requirement | Solution |
|-------------|----------|
| Mutual exclusion | `SET NX PX` |
| Crash recovery | TTL auto-expiry |
| Unambiguous ownership | Unique `owner_id` + atomic Lua release |
| **Prevent stale writes** | **Monotonic fencing tokens enforced by the resource** |
| Long operations | Watchdog renewal |
| Strict token monotonicity | Persistent/consistent token source |

The essential insight: **a lock cannot guarantee safety by itself under unbounded pauses — the protected resource must reject out-of-order (stale) tokens.**
</details>
