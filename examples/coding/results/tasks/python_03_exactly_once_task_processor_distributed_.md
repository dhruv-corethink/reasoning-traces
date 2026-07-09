# Exactly-Once Task Processor (Distributed Systems)

**Category:** Python / systems coding · `python_03_exactly_once_task_processor_distributed_`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **1** |
| Claude Haiku 4.5 + `/reason` | **3** |
| Delta | **+2** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Both submissions are incomplete and not runnable; critical pieces of the worker/processing loop and recovery are missing. Candidate B is closer to satisfying the requirements by using Redis Streams with consumer groups and atomic Lua scripts for leasing and idempotent completion, whereas Candidate A lacks a worker implementation and coherent recovery/dedup integration.

---

## Task
Implement a distributed task processor in Python using Redis. Multiple workers consume tasks concurrently, tasks may be delivered more than once, and workers may crash mid-execution. Each task must be executed exactly once. Handle duplicate deliveries, worker crashes, and safely retry stuck tasks without duplicating side effects.

---

## WITHOUT — Claude Haiku 4.5 alone
# Distributed Task Processor with Redis

I'll implement a robust distributed task processor that handles duplicate deliveries, worker crashes, and ensures exactly-once execution semantics.

```python
import json
import logging
import signal
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, Optional

import redis
from redis import Redis
from redis.exceptions import RedisError, LockError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class TaskPriority(Enum):
    """Task priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Task:
    """Represents a task to be executed."""
    id: str
    task_type: str
    payload: Dict[str, Any]
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 3
    timeout: int = 300  # seconds
    created_at: str = None
    
    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary."""
        data = asdict(self)
        data['priority'] = self.priority.value
        return data
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Task':
        """Create task from dictionary."""
        data_copy = data.copy()
        if isinstance(data_copy.get('priority'), str):
            data_copy['priority'] = TaskPriority(data_copy['priority'])
        return Task(**data_copy)


@dataclass
class TaskResult:
    """Task execution result."""
    task_id: str
    status: TaskStatus
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempt: int = 0
    executed_at: str = None
    duration_ms: float = 0.0
    
    def __post_init__(self):
        if self.executed_at is None:
            self.executed_at = datetime.utcnow().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'TaskResult':
        """Create result from dictionary."""
        data_copy = data.copy()
        if isinstance(data_copy.get('status'), str):
            data_copy['status'] = TaskStatus(data_copy['status'])
        return TaskResult(**data_copy)


class TaskHandler(ABC):
    """Base class for task handlers."""
    
    @abstractmethod
    def handle(self, task: Task) -> Dict[str, Any]:
        """
        Execute the task.
        
        Args:
            task: Task to execute
            
        Returns:
            Result dictionary
            
        Raises:
            Exception: Task execution failed
        """
        pass
    
    @property
    @abstractmethod
    def task_type(self) -> str:
        """Task type this handler handles."""
        pass


class IdempotencyStore:
    """
    Manages idempotency keys to ensure exactly-once execution.
    Stores the result of completed tasks to return on duplicates.
    """
    
    def __init__(self, redis_client: Redis, key_prefix: str = "idempotency"):
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.ttl = 86400  # 24 hours
    
    def _get_key(self, task_id: str) -> str:
        """Get idempotency key for task."""
        return f"{self.key_prefix}:{task_id}"
    
    def get_result(self, task_id: str) -> Optional[TaskResult]:
        """
        Get cached result if task was already completed.
        
        Args:
            task_id: Task ID
            
        Returns:
            TaskResult if found, None otherwise
        """
        try:
            key = self._get_key(task_id)
            data = self.redis.get(key)
            if data:
                result_dict = json.loads(data)
                return TaskResult.from_dict(result_dict)
            return None
        except RedisError as e:
            logger.error(f"Error retrieving idempotency result: {e}")
            return None
    
    def store_result(self, task_id: str, result: TaskResult) -> bool:
        """
        Store task result for deduplication.
        
        Args:
            task_id: Task ID
            result: Task result
            
        Returns:
            True if stored successfully
        """
        try:
            key = self._get_key(task_id)
            data = json.dumps(result.to_dict())
            self.redis.setex(key, self.ttl, data)
            return True
        except RedisError as e:
            logger.error(f"Error storing idempotency result: {e}")
            return False


class TaskQueue:
    """Redis-based task queue with priority support."""
    
    def __init__(self, redis_client: Redis, queue_name: str = "tasks"):
        self.redis = redis_client
        self.queue_name = queue_name
    
    def enqueue(self, task: Task) -> bool:
        """
        Enqueue a task.
        
        Args:
            task: Task to enqueue
            
        Returns:
            True if successful
        """
        try:
            # Use priority as score for sorted set
            score = -task.priority.value  # Negative for high-priority first
            data = json.dumps(task.to_dict())
            self.redis.zadd(self.queue_name, {data: score})
            logger.info(f"Task enqueued: {task.id}")
            return True
        except RedisError as e:
            logger.error(f"Error enqueueing task: {e}")
            return False
    
    def dequeue(self, timeout: int = 1) -> Optional[Task]:
        """
        Dequeue a task (FIFO with priority).
        
        Args:
            timeout: Blocking timeout in seconds
            
        Returns:
            Task if available, None if timeout
        """
        try:
            # Get highest priority task (lowest score)
            result = self.redis.bzpopmin(
                self.queue_name,
                timeout=timeout
            )
            if result:
                _, data, _ = result
                task_dict = json.loads(data)
                return Task.from_dict(task_dict)
            return None
        except RedisError as e:
            logger.error(f"Error dequeueing task: {e}")
            return None
    
    def queue_size(self) -> int:
        """Get current queue size."""
        try:
            return self.redis.zcard(self.queue_name)
        except RedisError:
            return 0


class ProcessingRegistry:
    """
    Tracks tasks being processed by workers.
    Used to detect stuck/crashed tasks.
    """
    
    def __init__(
        self,
        redis_client: Redis,
        key_prefix: str = "processing",
        timeout: int = 300
    ):
        self.redis = redis_client
        self.key_prefix = key_prefix
        self.timeout = timeout
    
    def _get_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:{task_id}"
    
    def register(self, task_id: str, worker_id: str) -> bool:
        """
        Register a task as being processed by a worker.
        
        Args:
            task_id: Task ID
            worker_id: Worker ID
            
        Returns:
            True if registered
        """
        try:
            key = self._get_key(task_id)
            data = json.dumps({
                'worker_id': worker_id,
                'timestamp': datetime.utcnow().isoformat()
            })
            # Set with timeout so it auto-expires if worker crashes
            self.redis.setex(key, self.timeout, data)
            return True
        except RedisError as e:
            logger.error(f"Error registering processing: {e}")
            return False
    
    def unregister(self, task_id: str) -> bool:
        """
        Unregister a task (completed or failed).
        
        Args:
            task_id: Task ID
            
        Returns:
            True if unregistered
        """
        try:
            key = self._get_key(task_id)
            self.redis.delete(key)
            return True
        except RedisError as e:
            logger.error(f"Error unregistering processing: {e}")
            return False
    
    def get_processing_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get processing info for a task."""
        try:
            key = self._get_key(task_id)
            data = self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except RedisError:
            return None
    
    def get_stuck_tasks(self) -> list:
        """Get all tasks that are stuck (still in registry)."""
        try:
            pattern = f"{self.key_prefix}:*"
            keys = self.redis.keys(pattern)
            stuck_tasks = []
            for key in keys:
                data = self.redis.get(key)
                if data:
                    task_id = key.decode().split(':')[1]
                    stuck_tasks.append({
                        'task_id': task_id,
                        'info': json.loads(data)
                    })
            return stuck_tasks
        except RedisError as e:
            logger.error(f"Error getting stuck tasks: {e}")
            return []


class TaskStateStore:
    """Stores task state and execution history."""
    
    def __init__(self, redis_client: Redis, key_prefix: str = "task_state"):
        self.redis = redis_client
        self.key_prefix = key_prefix
    
    def _get_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:{task_id}"
    
    def _get_history_key(self, task_id: str) -> str:
        return f"{self.key_prefix}:{task_id}:history"
    
    def save_state(
        

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Distributed Task Processor with Redis

I'll implement a production-grade distributed task processor that handles exactly-once execution semantics through atomic state management, idempotent handlers, and crash recovery.

```python
import json
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any

import redis
from redis.exceptions import ResponseError, RedisError

log = logging.getLogger("taskproc")
log.addHandler(logging.StreamHandler())

# ============================================================================
# Lua Scripts for Atomic Operations
# ============================================================================

# Acquire processing lease: returns "done" | "locked" | "acquired"
_LUA_ACQUIRE = """
local key, worker, lease_ms, now = KEYS[1], ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3])
local status = redis.call('HGET', key, 'status')

-- Already completed: idempotent duplicate
if status == 'done' then
    return 'done'
end

-- Check if lease is still active
local expires_at = tonumber(redis.call('HGET', key, 'expires_at') or '0')
if status == 'processing' and now < expires_at then
    return 'locked'
end

-- Acquire new lease
redis.call('HSET', key, 'status', 'processing', 'owner', worker, 'expires_at', now + lease_ms)
redis.call('PEXPIRE', key, lease_ms * 20)
return 'acquired'
"""

# Renew lease: returns 1 (success) | 0 (lost ownership)
_LUA_RENEW = """
local key, worker, lease_ms, now = KEYS[1], ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3])

-- Only renew if we still own the lease
if redis.call('HGET', key, 'owner') ~= worker then
    return 0
end
if redis.call('HGET', key, 'status') ~= 'processing' then
    return 0
end

redis.call('HSET', key, 'expires_at', now + lease_ms)
redis.call('PEXPIRE', key, lease_ms * 20)
return 1
"""

# Commit task completion: returns "ok" | "lost"
_LUA_COMPLETE = """
local key, worker, result, ttl_ms = KEYS[1], ARGV[1], ARGV[2], tonumber(ARGV[3])

-- Verify we still own the lease
if redis.call('HGET', key, 'owner') ~= worker then
    return 'lost'
end

-- Mark as done and store result
redis.call('HSET', key, 'status', 'done', 'result', result)
redis.call('HDEL', key, 'owner', 'expires_at')
redis.call('PEXPIRE', key, ttl_ms)
return 'ok'
"""

# Release lease on failure
_LUA_RELEASE = """
local key, worker = KEYS[1], ARGV[1]

if redis.call('HGET', key, 'owner') ~= worker then
    return 0
end

redis.call('HDEL', key, 'owner', 'expires_at')
redis.call('HSET', key, 'status', 'failed')
return 1
"""

# ============================================================================
# Data Models
# ============================================================================

@dataclass
class Task:
    """Represents a task to be processed."""
    id: str
    name: str
    payload: dict
    msg_id: str = ""
    deliveries: int = 1

    def __repr__(self):
        return (f"Task(id={self.id}, name={self.name}, "
                f"msg_id={self.msg_id}, deliveries={self.deliveries})")


@dataclass
class TaskResult:
    """Result of task execution."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ============================================================================
# Task Queue (Producer)
# ============================================================================

class TaskQueue:
    """Produces tasks to the Redis stream."""

    def __init__(
        self,
        r: redis.Redis,
        stream: str = "tasks",
        group: str = "workers"
    ):
        self.r = r
        self.stream = stream
        self.group = group

    def ensure_group(self):
        """Create consumer group if it doesn't exist."""
        try:
            self.r.xgroup_create(self.stream, self.group, id="0", mkstream=True)
            log.info(f"Created consumer group '{self.group}'")
        except ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def submit(
        self,
        name: str,
        payload: dict,
        task_id: Optional[str] = None
    ) -> str:
        """
        Enqueue a task for processing.

        Args:
            name: Task type/handler name
            payload: Task data (must be JSON-serializable)
            task_id: Idempotency key. Reuse for logical retries; generate fresh for new work.
                    If same task_id submitted twice, handler is called once.

        Returns:
            task_id of the submitted task
        """
        task_id = task_id or str(uuid.uuid4())
        msg_id = self.r.xadd(
            self.stream,
            {
                "id": task_id,
                "name": name,
                "payload": json.dumps(payload),
            }
        )
        log.debug(f"Submitted task {task_id} ({name}) -> stream entry {msg_id}")
        return task_id

    def get_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of a task."""
        key = f"task:state:{task_id}"
        state = self.r.hgetall(key)
        if not state:
            return None
        return {
            k.decode() if isinstance(k, bytes) else k:
            v.decode() if isinstance(v, bytes) else v
            for k, v in state.items()
        }


# ============================================================================
# Worker (Consumer)
# ============================================================================

class Worker:
    """Processes tasks from the Redis stream with exactly-once semantics."""

    def __init__(
        self,
        r: redis.Redis,
        handler: Callable[[Task], TaskResult],
        stream: str = "tasks",
        group: str = "workers",
        name: Optional[str] = None,
        lease_ms: int = 30_000,
        heartbeat_ms: int = 10_000,
        claim_idle_ms: int = 60_000,
        result_ttl_ms: int = 24 * 3600 * 1000,
        max_attempts: int = 5,
        block_ms: int = 5_000,
        batch: int = 10,
    ):
        """
        Initialize a worker.

        Args:
            r: Redis client
            handler: Async function(Task) -> TaskResult. MUST be idempotent on task.id.
            stream: Redis stream name
            group: Consumer group name
            name: Worker identifier (auto-generated if None)
            lease_ms: Max milliseconds a task execution can hold the lease
            heartbeat_ms: Interval to renew the lease while processing
            claim_idle_ms: Idle time threshold for reclaiming abandoned messages
                          MUST be > lease_ms so expired leases are reclaimed first
            result_ttl_ms: How long to keep 'done' state for deduplication
            max_attempts: Max delivery attempts before dead-lettering
            block_ms: Redis XREADGROUP block timeout
            batch: Messages to read per batch
        """
        assert claim_idle_ms > lease_ms, (
            f"claim_idle_ms ({claim_idle_ms}) must exceed lease_ms ({lease_ms}) "
            "so expired leases are reclaimed before duplicate deliveries"
        )

        self.r = r
        self.handler = handler
        self.stream = stream
        self.group = group
        self.name = name or self._generate_name()
        self.lease_ms = lease_ms
        self.heartbeat_ms = heartbeat_ms
        self.claim_idle_ms = claim_idle_ms
        self.result_ttl_ms = result_ttl_ms
        self.max_attempts = max_attempts
        self.block_ms = block_ms
        self.batch = batch
        self._stop = threading.Event()
        self._current_task: Optional[Task] = None

        # Register Lua scripts
        self._acquire_script = r.register_script(_LUA_ACQUIRE)
        self._renew_script = r.register_script(_LUA_RENEW)
        self._complete_script = r.register_script(_LUA_COMPLETE)
        self._release_script = r.register_script(_LUA_RELEASE)

        log.info(f"Worker '{self.name}' initialized")

    @staticmethod
    def _generate_name() -> str:
        """Generate a unique worker name."""
        return (f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}")

    def stop(self):
        """Signal the worker to stop gracefully."""
        self._stop.set()
        log.info(f"Worker '{self.name}' stop signal sent")

    def run(self):
        """Main worker loop: consume and process tasks."""
        TaskQueue(self.r, self.stream, self.group).ensure_group()
        log.info(f"Worker '{self.name}' started (lease={self.lease_ms}ms, "
                 f"claim_idle={self.claim_idle_ms}ms)")

        while not self._stop.is_set():
            try:
                # Reclaim tasks from crashed workers (crash recovery)
                self._reclaim_stuck_tasks()

                # Read newly delivered messages
                claimed = self._read_new_messages()

                # If idle, wait a bit before next iteration
                if not claimed and not self._stop.is_set():
                    time.sleep(0.5)

            except RedisError as e:
                log.exception(f"Redis error in worker loop: {e}")
                time.sleep(1)
            except Exception as e:
                log.exception(f"Unexpected error in worker loop: {e}")
                time.sleep(1)

        log.info(f"Worker '{self.name}' stopped")

    # ========================================================================
    # Read New Messages
    # ========================================================================

    def _read_new_messages(self) -> int:
        """Read newly delivered messages from the stream."""
        resp = self.r.xreadgroup(
            self.group, self.name,
            {self.stream: ">"},
            count=self.batch,
            block=self.block_ms,
        )

        n = 0
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                n += 1
                task = self._parse_message

---

<details><summary>Reasoning trace supplied to Haiku</summary>

I need to design a distributed task processor using Redis that handles concurrent workers, at-least-once delivery semantics, and worker failures while ensuring each task executes exactly once. The key challenges are managing duplicate deliveries through idempotency, recovering from worker crashes using visibility timeouts, and safely retrying stuck tasks without creating duplicate side effects.

I'll use Redis Streams with consumer groups for the queue, since it provides built-in acknowledgment and message claiming for crash recovery. For exactly-once semantics, I'll track task state atomically (pending → in-progress → completed) and make side effects idempotent by using the task ID as a deduplication key. A separate recovery process will periodically reclaim messages that have been pending too long, allowing other workers to retry them.

The core logic: when a worker picks up a task, it atomically acquires a processing lock with an expiration time; if the worker crashes, the lock expires and another worker can reclaim and retry. The side effect must be idempotent since there's an unavoidable window where a worker could execute it but crash before marking the task done. I'll implement a task producer, a worker consumer with exactly-once semantics, recovery via XAUTOCLAIM, and Lua scripts for atomic operations.

Writing Lua scripts... Writing the implementation... Writing the core classes... The dedup state is keyed by task ID, not message ID, so when the same task gets enqueued twice with different message IDs, two workers can legitimately receive separate messages. If worker B encounters a 'done' state, it should ack its duplicate. If it sees 'locked' (worker A still processing), B could ack too since it's a genuine duplicate and A's lease will handle recovery independently if A crashes. The tricky part is deciding whether B should ack or leave the message pending when locked—acking is simpler and safe since each message ID has its own entry in the pending list, but leaving it pending risks B re-reading it indefinitely until the lock clears.

The real guarantee comes from configuring the claim idle timeout longer than the lease duration. If A crashes after acquiring the lease, its message sits idle until the claim window triggers, at which point B can claim it via XAUTOCLAIM. By then, if the lease duration is shorter than the claim idle window, the lease will have expired and B can acquire it fresh. So the key is setting claim_idle_ms greater than lease_ms to ensure the lease expires before B takes over. Meanwhile, if A stays alive, heartbeat renewals keep the lease active. Writing the complete solution...

**Conclusion:** # Distributed Exactly-Once Task Processor (Redis)

Before code, the honest engineering reality: **true "exactly once" execution is impossible** in a distributed system where a worker can crash at *any* instruction. What we *can* build is **effectively-once**:

```
at-least-once delivery  +  atomic dedup/lease  +  idempotent side effects  =  effectively once
```

## Design

| Concern | Mechanism |
|---|---|
| Queue + concurrent consumers | **Redis Streams** + consumer group (`XREADGROUP`) |
| At-least-once delivery / crash recovery | Unacked messages stay in the **PEL**; reclaimed via `XAUTOCLAIM` |
| Duplicate deliveries | Per-task **state key** (`done` short-circuits) |
| Two workers racing on same task | Atomic **lease** (owner + expiry) via Lua |
| Worker crash mid-task | Lease **expires** → message reclaimed → retried |
| No duplicated side effects | Lease + `done` marker + **idempotent handler** (uses `task_id` as idempotency key) |

The one unavoidable gap — crash *after* the external side effect but *before* the `done` marker — is closed by requiring the handler to be idempotent keyed on `task_id`. I make this the framework's central contract.

---

## Code

```python
import json
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

import redis

log = logging.getLogger("taskproc")

# --------------------------------------------------------------------------
# Atomic state transitions (Lua = executed atomically inside Redis)
# State key is a hash: {status, owner, expires_at, result}
#   status: "processing" | "done"
# --------------------------------------------------------------------------

# Acquire a processing lease. Returns: "done" | "locked" | "acquired"
_ACQUIRE = """
local key, worker, lease_ms, now = KEYS[1], ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3])
local status = redis.call('HGET', key, 'status')
if status == 'done' then return 'done' end
local expires = tonumber(redis.call('HGET', key, 'expires_at') or '0')
if status == 'processing' and now < expires then return 'locked' end
redis.call('HSET', key, 'status', 'processing', 'owner', worker, 'expires_at', now + lease_ms)
redis.call('PEXPIRE', key, lease_ms * 20)   -- keep state alive beyond the lease
return 'acquired'
"""

# Heartbeat: extend lease only if we still own it. Returns 1/0.
_RENEW = """
local key, worker, lease_ms, now = KEYS[1], ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3])
if redis.call('HGET', key, 'owner') ~= worker then return 0 end
if redis.call('HGET', key, 'status') ~= 'processing' then return 0 end
redis.call('HSET', key, 'expires_at', now + lease_ms)
redis.call('PEXPIRE', key, lease_ms * 20)
return 1
"""

# Commit: mark done + store result, ONLY if we still own the lease.
# Returns "ok" | "lost"
_COMPLETE = """
local key, worker, result, ttl_ms = KEYS[1], ARGV[1], ARGV[2], tonumber(ARGV[3])
if redis.call('HGET', key, 'owner') ~= worker then return 'lost' end
redis.call('HSET', key, 'status', 'done', 'result', result)
redis.call('HDEL', key, 'owner', 'expires_at')
redis.call('PEXPIRE', key, ttl_ms)          -- keep 'done' marker for dedup window
return 'ok'
"""

# Release lease on failure so another worker can retry sooner. Returns 1/0.
_RELEASE = """
local key, worker = KEYS[1], ARGV[1]
if redis.call('HGET', key, 'owner') ~= worker then return 0 end
redis.call('HDEL', key, 'owner', 'expires_at')
redis.call('HSET', key, 'status', 'failed')
return 1
"""


@dataclass
class Task:
    id: str
    name: str
    payload: dict
    msg_id: str = ""      # stream entry id (set on consume)
    deliveries: int = 1   # attempt count from the stream PEL


def _state_key(task_id: str) -> str:
    return f"task:state:{task_id}"


# --------------------------------------------------------------------------
# Producer
# --------------------------------------------------------------------------
class TaskQueue:
    def __init__(self, r: redis.Redis, stream: str = "tasks", group: str = "workers"):
        self.r = r
        self.stream = stream
        self.group = group

    def ensure_group(self):
        try:
            self.r.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def submit(self, name: str, payload: dict, task_id: Optional[str] = None) -> str:
        """Enqueue a task. task_id is the idempotency key; reuse it for a
        logical retry, generate a fresh one for a distinct piece of work."""
        task_id = task_id or str(uuid.uuid4())
        self.r.xadd(self.stream, {
            "id": task_id,
            "name": name,
            "payload": json.dumps(payload),
        })
        return task_id


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------
class Worker:
    def __init__(
        self,
        r: redis.Redis,
        handler: Callable[[Task], dict],
        stream: str = "tasks",
        group: str = "workers",
        name: Optional[str] = None,
        lease_ms: int = 30_000,        # how long one attempt may run before lease expires
        heartbeat_ms: int = 10_000,    # renew lease every N ms while working
        claim_idle_ms: int = 60_000,   # reclaim messages idle longer than this
        result_ttl_ms: int = 24 * 3600 * 1000,
        max_attempts: int = 5,
        block_ms: int = 5_000,
        batch: int = 10,
    ):
        assert claim_idle_ms > lease_ms, "claim_idle must exceed lease so crashed leases expire first"
        self.r = r
        self.handler = handler
        self.stream, self.group = stream, group
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.lease_ms = lease_ms
        self.heartbeat_ms = heartbeat_ms
        self.claim_idle_ms = claim_idle_ms
        self.result_ttl_ms = result_ttl_ms
        self.max_attempts = max_attempts
        self.block_ms = block_ms
        self.batch = batch
        self._stop = threading.Event()

        self._acquire = r.register_script(_ACQUIRE)
        self._renew = r.register_script(_RENEW)
        self._complete = r.register_script(_COMPLETE)
        self._release = r.register_script(_RELEASE)

    def stop(self):
        self._stop.set()

    # ---- main loop --------------------------------------------------------
    def run(self):
        TaskQueue(self.r, self.stream, self.group).ensure_group()
        log.info("worker %s started", self.name)
        while not self._stop.is_set():
            try:
                self._reclaim_stuck()          # crash recovery
                claimed = self._read_new()     # fresh work
                if not claimed:
                    continue
            except redis.RedisError:
                log.exception("redis error; backing off")
                time.sleep(1)

    # ---- read newly-delivered messages ------------------------------------
    def _read_new(self) -> int:
        resp = self.r.xreadgroup(
            self.group, self.name,
            {self.stream: ">"},
            count=self.batch, block=self.block_ms,
        )
        n = 0
        for _stream, entries in resp or []:
            for msg_id, fields in entries:
                n += 1
                self._handle(self._parse(msg_id, fields, deliveries=1))
        return n

    # ---- reclaim messages abandoned by crashed workers --------------------
    def _reclaim_stuck(self):
        cursor = "0-0"
        while True:
            cursor, entries, _ = self.r.xautoclaim(
                self.stream, self.group, self.name,
                min_idle_time=self.claim_idle_ms,
                start_id=cursor, count=self.batch,
            )
            for msg_id, fields in entries:
                if not fields:                 # message was deleted; drop from PEL
                    self.r.xack(self.stream, self.group, msg_id)
                    continue
                deliveries = self._delivery_count(msg_id)
                self._handle(self._parse(msg_id, fields, deliveries))
            if cursor == "0-0" or not entries:
                break

    # ---- core: process one message exactly once ---------------------------
    def _handle(self, task: Task):
        key = _state_key(task.id)
        now = int(time.time() * 1000)
        state = self._acquire(keys=[key], args=[self.name, self.lease_ms, now])

        if state == b"done":
            # Duplicate delivery of an already-completed task -> just ack.
            self._ack(task.msg_id)
            return
        if state == b"locked":
            # Another live worker owns the lease. The task WILL be driven to
            # completion via that owner's lease (or its message reclaim).
            # This is a genuine duplicate copy -> safe to ack.
            self._ack(task.msg_id)
            return

        # state == b"acquired": we own the lease for this task.
        if task.deliveries > self.max_attempts:
            log.error("task %s exceeded max attempts -> dead-letter", task.id)
            self._dead_letter(task)
            self._complete(keys=[key], args=[self.name, "DEAD_LETTER", self.result_ttl_ms])
            self._ack(task.msg_id)
            return

        stop_hb = threading.Event()
        hb = threading.Thread(target=self._heartbeat, args=(key, stop_hb), daemon=True)
        hb.start()
        try:
            # === user side effect ===
            # CONTRACT: handler MUST be idempotent, keyed on task.id, because a
            # crash between here and _complete() causes a retry.
            result = self.handler(task)

            res = self._complete(
                keys=[key],
                args=[self.name, json.dumps(result or {}), self.result_ttl_ms],
            )
            if res == b"ok":
                self._ack(task.msg_id)   # commit point
            else:
                # We lost the lease mid-flight (we were too slow). Do NOT ack;
                # the new owner is authoritative. Our idempotent handler made
                # the double-run harmless.
                log.warning("lost lease for %s during execution", task.id)
        except Exception:
            log.exception("handler failed for task %s", task.id)
            # Release lease so a retry can happen quickly; leave msg unacked so
            # it stays in the PEL and gets reclaimed / redelivered.
            self._release(keys=[key], args=[self.name])
        finally:
            stop_hb.set()
            hb.join(timeout=1)

    # ---- lease heartbeat --------------------------------------------------
    def _heartbeat(self, key: str, stop: threading.Event):
        while not stop.wait(self.heartbeat_ms / 1000):
            now = int(time.time() * 1000)
            if self._renew(keys=[key], args=[self.name, self.lease_ms, now]) == 0:
                return  # lost ownership; stop renewing

    # ---- helpers ----------------------------------------------------------
    def _ack(self, msg_id: str):
        self.r.xack(self.stream, self.group, msg_id)

    def _delivery_count(self, msg_id: str) -> int:
        info = self.r.xpending_range(self.stream, self.group, msg_id, msg_id, 1)
        return info[0]["times_delivered"] if info else 1

    def _dead_letter(self, task: Task):
        self.r.xadd(f"{self.stream}:dead", {
            "id": task.id, "name": task.name,
            "payload": json.dumps(task.payload),
            "deliveries": task.deliveries,
        })

    @staticmethod
    def _parse(msg_id, fields, deliveries) -> Task:
        d = {k.decode() if isinstance(k, bytes) else k:
             v.decode() if isinstance(v, bytes) else v
             for k, v in fields.items()}
        mid = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
        return Task(
            id=d["id"], name=d["name"],
            payload=json.loads(d.get("payload", "{}")),
            msg_id=mid, deliveries=deliveries,
        )
```

---

## Usage

```python
import redis, threading, time, logging
logging.basicConfig(level=logging.INFO)

r = redis.Redis()

# ---- idempotent handler ----------------------------------------------------
def handle(task: Task) -> dict:
    # Example side effect: charge a payment. It MUST be idempotent on task.id.
    # e.g. Stripe: client.PaymentIntent.create(..., idempotency_key=task.id)
    #      SQL:    INSERT ... ON CONFLICT (task_id) DO NOTHING
    print(f"[{task.name}] running {task.id} (attempt {task.deliveries})")
    time.sleep(0.2)
    return {"charged": task.payload.get("amount")}

# ---- produce ---------------------------------------------------------------
q = TaskQueue(r)
q.ensure_group()
for i in range(20):
    q.submit("charge", {"amount": i})

# duplicate deliveries: same task_id submitted twice -> executed once
dup = q.submit("charge", {"amount": 999})
q.submit("charge", {"amount": 999}, task_id=dup)

# ---- run several concurrent workers ----------------------------------------
workers = [Worker(r, handle) for _ in range(4)]
threads = [threading.Thread(target=w.run, daemon=True) for w in workers]
for t in threads: t.start()

time.sleep(5)
for w in workers: w.stop()
```

---

## How each requirement is met

- **Duplicate deliveries** — `_ACQUIRE` returns `done` (already executed → ack) or `locked` (another owner is handling it → ack the redundant copy). Both short-circuit before any side effect.
- **Worker crashes mid-execution** — the crashed worker stops heartbeating; its lease expires (`expires_at`), and its unacked stream entry sits in the PEL. `XAUTOCLAIM` (with `min_idle_time > lease_ms`) transfers it to a healthy worker, which re-acquires the now-expired lease and retries.
- **Exactly-once effect** — a single atomic lease per `task_id` ensures only one worker executes at a time; the `done` marker plus `result` are written atomically at the commit point.
- **Safe retry without duplicate side effects** — the unavoidable "crashed after side effect, before commit" window is neutralized by the **handler idempotency contract** (`task_id` as the idempotency key downstream). Poison tasks are capped by `max_attempts` and routed to a dead-letter stream.

## Production notes
- Requires Redis ≥ 6.2 (`XAUTOCLAIM`).
- Run reclaim on a timer/dedicated reaper if you want faster recovery than the read loop cadence.
- Set `lease_ms` above your P99 task duration; a task that outlives its lease will be taken over (harmless given idempotency, but wasteful).
- For strict correctness the handler’s idempotency store and its side effect should share a transaction (same DB), or use the external system’s native idempotency key — Redis alone cannot make an arbitrary external effect atomic with the `done` marker.
</details>
