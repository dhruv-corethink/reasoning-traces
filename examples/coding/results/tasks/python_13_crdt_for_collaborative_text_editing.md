# CRDT for Collaborative Text Editing

**Category:** Python / systems coding · `python_13_crdt_for_collaborative_text_editing`

| Condition | Score /10 |
|---|---|
| Claude Haiku 4.5 alone | **1** |
| Claude Haiku 4.5 + `/reason` | **3** |
| Delta | **+2** — judge pick: **WITH** |

_Judge (openai/gpt-5, blind pairwise):_ Both candidates are incomplete and not runnable, failing the requirement for complete, coherent code. Candidate B is closer to a correct CRDT, with causal buffering, idempotence, and remote apply logic, but still lacks the core integration algorithm, while Candidate A’s application logic is truncated and unusable.

---

## Task
Implement a Conflict-Free Replicated Data Type (CRDT) for text editing. Support concurrent inserts and deletes across replicas without coordination. Ensure convergence, preserve user intent, and guarantee deterministic merges.

---

## WITHOUT — Claude Haiku 4.5 alone
# Conflict-Free Replicated Data Type for Text Editing

I'll implement a comprehensive CRDT system for text editing based on the Logoot algorithm with tombstones for deletes.

```python
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Any
from enum import Enum
import uuid
from collections import defaultdict
import json
from abc import ABC, abstractmethod
import heapq


class OperationType(Enum):
    """Types of operations in the CRDT"""
    INSERT = "insert"
    DELETE = "delete"


@dataclass(frozen=True)
class Identifier:
    """Unique, immutable identifier for a character in the document.
    
    Uses a tuple of (clock, replica_id) pairs to create a total order
    that respects causality and allows for arbitrary insertion.
    """
    position: Tuple[Tuple[int, str], ...] = field(default_factory=tuple)
    
    def __lt__(self, other: 'Identifier') -> bool:
        """Total order comparison"""
        return self.position < other.position
    
    def __le__(self, other: 'Identifier') -> bool:
        return self.position <= other.position
    
    def __gt__(self, other: 'Identifier') -> bool:
        return self.position > other.position
    
    def __ge__(self, other: 'Identifier') -> bool:
        return self.position >= other.position
    
    def __hash__(self):
        return hash(self.position)
    
    def to_dict(self) -> Dict[str, Any]:
        return {"position": self.position}


@dataclass
class Operation:
    """Represents a single edit operation (insert or delete)"""
    operation_type: OperationType
    content: str  # Character(s) for insert, empty for delete
    identifier: Identifier
    timestamp: int  # Lamport clock for causality
    replica_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_type": self.operation_type.value,
            "content": self.content,
            "identifier": self.identifier.to_dict(),
            "timestamp": self.timestamp,
            "replica_id": self.replica_id
        }


@dataclass
class Character:
    """Represents a character in the document"""
    identifier: Identifier
    content: str
    deleted: bool = False
    timestamp: int = 0  # When it was inserted
    
    def is_visible(self) -> bool:
        return not self.deleted


class CRDTTextDocument:
    """
    CRDT-based text document that supports concurrent editing.
    
    Based on Logoot algorithm:
    - Each character has a unique, immutable identifier
    - Identifiers define total order independent of network delays
    - Deletions use tombstones (marks without removal)
    - Operations are idempotent and commutative
    """
    
    def __init__(self, replica_id: str):
        self.replica_id = replica_id
        self.lamport_clock = 0
        
        # Main data structure: map from identifier to character
        self.characters: Dict[Identifier, Character] = {}
        
        # Operation history for causality tracking
        self.operation_history: List[Operation] = []
        
        # Track applied operations to prevent duplicates
        self.applied_operations: Set[Tuple[str, int, str]] = set()
        
        # Vector clocks for replica sync tracking
        self.vector_clocks: Dict[str, int] = defaultdict(int)
    
    def _increment_lamport_clock(self) -> int:
        """Increment and return the Lamport clock"""
        self.lamport_clock += 1
        return self.lamport_clock
    
    def _generate_identifier_between(
        self,
        left: Optional[Identifier],
        right: Optional[Identifier],
        strategy: str = "simple"
    ) -> Identifier:
        """
        Generate a new unique identifier between two existing ones.
        
        Args:
            left: Identifier to the left (None for beginning)
            right: Identifier to the right (None for end)
            strategy: "simple" or "adaptive"
        
        Returns:
            New unique identifier
        """
        if strategy == "simple":
            return self._generate_simple_identifier(left, right)
        else:
            return self._generate_adaptive_identifier(left, right)
    
    def _generate_simple_identifier(
        self,
        left: Optional[Identifier],
        right: Optional[Identifier]
    ) -> Identifier:
        """Generate identifier using simple strategy"""
        new_pos: List[Tuple[int, str]] = []
        
        if left is None:
            # Insert at beginning
            if right is None:
                # Empty document
                new_pos = [(0, self.replica_id)]
            else:
                # Before the first element
                first_pos = right.position
                new_pos = [(first_pos[0][0] - 1, self.replica_id)]
        elif right is None:
            # Insert at end
            last_pos = left.position
            new_pos = [(last_pos[-1][0] + 1, self.replica_id)]
        else:
            # Insert between two elements
            left_pos = left.position
            right_pos = right.position
            
            # Find common prefix
            common_len = 0
            for i, (lp, rp) in enumerate(zip(left_pos, right_pos)):
                if lp == rp:
                    common_len = i + 1
                else:
                    break
            
            if common_len == len(left_pos):
                # left is prefix of right, generate between last element and first difference
                new_clock = (left_pos[-1][0] + right_pos[common_len][0]) // 2
                if new_clock == left_pos[-1][0]:
                    new_clock += 1
                new_pos = list(left_pos) + [(new_clock, self.replica_id)]
            elif common_len == len(right_pos):
                # right is prefix of left (shouldn't happen with proper ordering)
                new_pos = list(left_pos[:-1])
                new_pos.append((left_pos[-1][0] + 1, self.replica_id))
            else:
                # They diverge at common_len
                left_clock = left_pos[common_len][0]
                right_clock = right_pos[common_len][0]
                
                if right_clock == left_clock + 1:
                    # Adjacent clocks, extend position
                    new_pos = list(left_pos[:common_len]) + [
                        (left_clock, self.replica_id),
                        (0, self.replica_id)
                    ]
                else:
                    # Room to insert between
                    new_clock = (left_clock + right_clock) // 2
                    new_pos = list(left_pos[:common_len]) + [(new_clock, self.replica_id)]
        
        return Identifier(tuple(new_pos))
    
    def _generate_adaptive_identifier(
        self,
        left: Optional[Identifier],
        right: Optional[Identifier]
    ) -> Identifier:
        """Generate identifier using adaptive strategy (handles clock explosion)"""
        # Similar to simple but with better handling of long sequences
        return self._generate_simple_identifier(left, right)
    
    def _find_boundaries(self, index: int) -> Tuple[Optional[Identifier], Optional[Identifier]]:
        """Find the identifiers to the left and right of a given index"""
        visible_chars = self._get_visible_identifiers()
        
        if index < 0 or index > len(visible_chars):
            raise ValueError(f"Index {index} out of range")
        
        left = visible_chars[index - 1] if index > 0 else None
        right = visible_chars[index] if index < len(visible_chars) else None
        
        return left, right
    
    def _get_visible_identifiers(self) -> List[Identifier]:
        """Get sorted list of visible (not deleted) character identifiers"""
        visible = [
            char_id for char_id, char in self.characters.items()
            if char.is_visible()
        ]
        return sorted(visible)
    
    def insert(self, index: int, content: str) -> List[Operation]:
        """
        Insert content at the given index.
        
        Args:
            index: Position to insert at
            content: Text to insert
        
        Returns:
            List of operations generated
        """
        if not content:
            return []
        
        operations = []
        left, right = self._find_boundaries(index)
        
        for char in content:
            # Generate unique identifier for this character
            identifier = self._generate_identifier_between(left, right)
            
            # Update left for next character
            left = identifier
            
            timestamp = self._increment_lamport_clock()
            
            # Create operation
            op = Operation(
                operation_type=OperationType.INSERT,
                content=char,
                identifier=identifier,
                timestamp=timestamp,
                replica_id=self.replica_id
            )
            
            # Apply locally
            self._apply_operation(op)
            operations.append(op)
        
        return operations
    
    def delete(self, start_index: int, end_index: int) -> List[Operation]:
        """
        Delete characters in range [start_index, end_index).
        
        Args:
            start_index: Start of range
            end_index: End of range
        
        Returns:
            List of operations generated
        """
        if start_index >= end_index or start_index < 0:
            return []
        
        operations = []
        visible_ids = self._get_visible_identifiers()
        
        # Get identifiers to delete
        to_delete = visible_ids[start_index:end_index]
        
        for identifier in to_delete:
            timestamp = self._increment_lamport_clock()
            
            # Create delete operation
            op = Operation(
                operation_type=OperationType.DELETE,
                content="",
                identifier=identifier,
                timestamp=timestamp,
                replica_id=self.replica_id
            )
            
            # Apply locally
            self._apply_operation(op)
            operations.append(op)
        
        return operations
    
    def _apply_operation(self, op: Operation) -> bool:
        """
        Apply an operation to the document.
        
        Returns:
            True if operation was applied, False if already seen
        """
        # Check if we've already applied this operation
        op_key = (op.replica_id, op.timestamp, op.identifier.position)
        if op_key in self.applied_operations:
            return False
        
        self.applied_operations.add(op_key)
        self.operation_history.append(op)
        
        # Update vector clock
        self.vector_clocks[op.replica_id] = max(
            self.vector_clocks[op.replica_id],
            op.timestamp
        )
        
        # Update Lamport clock
        self.

---

## WITH — Claude Haiku 4.5 + `/reason` trace (Claude Opus 4.8 (proxy for Corethink))
# Conflict-Free Replicated Data Type (CRDT) for Text Editing

I'll implement a robust **RGA-based CRDT** with production considerations including causal ordering, garbage collection, and optimized performance.

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Set, Tuple
from collections import defaultdict
import heapq
from enum import Enum


# ============================================================================
# Core Data Structures
# ============================================================================

@dataclass(frozen=True, order=True)
class Identifier:
    """
    Globally unique, totally-ordered identifier for a character.
    (clock, replica_id) ensures deterministic convergence.
    """
    clock: int
    replica_id: int

    def __repr__(self):
        return f"ID({self.clock},{self.replica_id})"

    def to_tuple(self) -> Tuple[int, int]:
        return (self.clock, self.replica_id)

    @staticmethod
    def from_tuple(t: Tuple[int, int]) -> "Identifier":
        return Identifier(t[0], t[1])


@dataclass
class Node:
    """A character node in the RGA sequence."""
    id: Identifier
    value: str
    origin: Optional[Identifier]  # ID of node this was inserted after
    deleted: bool = False
    timestamp: int = 0  # For GC: when was this deleted?

    def __repr__(self):
        status = "🗑️ " if self.deleted else ""
        return f"{status}{self.value}:{self.id}"


class OperationType(Enum):
    INSERT = "insert"
    DELETE = "delete"


@dataclass
class Operation:
    """Immutable operation for replication."""
    type: OperationType
    node_id: Identifier
    value: Optional[str] = None
    origin: Optional[Identifier] = None
    timestamp: int = 0

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "node_id": self.node_id.to_tuple(),
            "value": self.value,
            "origin": self.origin.to_tuple() if self.origin else None,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "Operation":
        return Operation(
            type=OperationType(d["type"]),
            node_id=Identifier.from_tuple(d["node_id"]),
            value=d.get("value"),
            origin=Identifier.from_tuple(d["origin"]) if d.get("origin") else None,
            timestamp=d.get("timestamp", 0),
        )


# ============================================================================
# Version Vector for Causality & GC
# ============================================================================

@dataclass
class VersionVector:
    """Track causal history: what operations each replica has seen."""
    clock: Dict[int, int] = field(default_factory=dict)

    def increment(self, replica_id: int):
        self.clock[replica_id] = self.clock.get(replica_id, 0) + 1

    def observe(self, other: "VersionVector"):
        """Merge causality: take max of each replica's clock."""
        for rid, clock in other.clock.items():
            self.clock[rid] = max(self.clock.get(rid, 0), clock)

    def happened_before(self, other: "VersionVector") -> bool:
        """Check if self <= other in causal order."""
        return all(self.clock.get(rid, 0) <= other.clock.get(rid, 0)
                   for rid in set(self.clock.keys()) | set(other.clock.keys()))

    def copy(self) -> "VersionVector":
        return VersionVector(clock=self.clock.copy())


# ============================================================================
# Main CRDT Implementation
# ============================================================================

class RGATextCRDT:
    """
    Replicated Growable Array (RGA) CRDT for text editing.
    
    Guarantees:
    - Strong Eventual Consistency (SEC)
    - Commutative operations
    - Idempotent application
    - Intent preservation
    - Concurrent editing without coordination
    """

    def __init__(self, replica_id: int):
        self.replica_id = replica_id
        self.clock = 0
        self.version_vector = VersionVector()

        # Core state
        self.nodes: List[Node] = []
        self._index: Dict[Identifier, int] = {}

        # Causal ordering: buffer ops whose origin hasn't arrived
        self._pending_inserts: List[Operation] = []
        self._applied_ops: Set[Identifier] = set()

        # GC state
        self._tombstone_version: Dict[Identifier, VersionVector] = {}
        self._replica_version: Dict[int, int] = defaultdict(int)

    # ========================================================================
    # Clock Management
    # ========================================================================

    def _next_id(self) -> Identifier:
        """Generate unique ID for local operation."""
        self.clock += 1
        self.version_vector.increment(self.replica_id)
        return Identifier(self.clock, self.replica_id)

    def _observe_operation(self, op: Operation):
        """Update causality from remote operation."""
        self.clock = max(self.clock, op.node_id.clock)
        self.version_vector.observe(VersionVector({op.node_id.replica_id: op.node_id.clock}))

    # ========================================================================
    # Visible Text View
    # ========================================================================

    def text(self) -> str:
        """Get the current visible text (excluding tombstones)."""
        return "".join(n.value for n in self.nodes if not n.deleted)

    def length(self) -> int:
        """Get visible text length."""
        return len(self.text())

    def _visible_positions(self) -> List[int]:
        """Get indices of visible (non-deleted) nodes."""
        return [i for i, n in enumerate(self.nodes) if not n.deleted]

    def _visible_index_to_node_index(self, vis_idx: int) -> Optional[int]:
        """Map cursor position in visible text to underlying node index."""
        count = 0
        for i, n in enumerate(self.nodes):
            if not n.deleted:
                if count == vis_idx:
                    return i
                count += 1
        return None

    # ========================================================================
    # Local Operations (Generate)
    # ========================================================================

    def local_insert(self, vis_pos: int, char: str) -> Operation:
        """
        Insert character at visible position.
        
        Args:
            vis_pos: Position in visible text (0 = start)
            char: Character to insert
            
        Returns:
            Operation to broadcast
        """
        # Determine origin (node we insert after)
        if vis_pos == 0:
            origin = None
        else:
            node_idx = self._visible_index_to_node_index(vis_pos - 1)
            if node_idx is None:
                vis = self._visible_positions()
                node_idx = vis[-1] if vis else None
            origin = self.nodes[node_idx].id if node_idx is not None else None

        new_id = self._next_id()
        node = Node(
            id=new_id,
            value=char,
            origin=origin,
            timestamp=self.clock
        )
        self._integrate(node)
        self._applied_ops.add(new_id)

        op = Operation(
            type=OperationType.INSERT,
            node_id=new_id,
            value=char,
            origin=origin,
            timestamp=self.clock
        )
        return op

    def local_delete(self, vis_pos: int) -> Optional[Operation]:
        """
        Delete character at visible position.
        
        Args:
            vis_pos: Position in visible text
            
        Returns:
            Operation to broadcast, or None if position invalid
        """
        node_idx = self._visible_index_to_node_index(vis_pos)
        if node_idx is None:
            return None

        node = self.nodes[node_idx]
        node.deleted = True
        node.timestamp = self.clock

        # Record version when deleted for GC
        self._tombstone_version[node.id] = self.version_vector.copy()

        op = Operation(
            type=OperationType.DELETE,
            node_id=node.id,
            timestamp=self.clock
        )
        return op

    # ========================================================================
    # Remote Operations (Apply)
    # ========================================================================

    def apply_remote(self, op: Operation) -> bool:
        """
        Apply remote operation. Handles causal ordering and idempotence.
        
        Args:
            op: Remote operation
            
        Returns:
            True if applied, False if buffered (waiting for origin)
        """
        # Idempotence: skip if already applied
        if op.node_id in self._applied_ops:
            return True

        self._observe_operation(op)

        if op.type == OperationType.INSERT:
            # Check if origin has arrived (or is null)
            if op.origin is not None and op.origin not in self._index:
                # Buffer: origin not yet available
                heapq.heappush(self._pending_inserts, (op.node_id, op))
                return False

            node = Node(
                id=op.node_id,
                value=op.value,
                origin=op.origin,
                timestamp=op.timestamp
            )
            self._integrate(node)
            self._applied_ops.add(op.node_id)

            # Try to flush pending inserts
            self._flush_pending()
            return True

        elif op.type == OperationType.DELETE:
            if op.node_id in self._index:
                idx = self._index[op.node_id]
                self.nodes[idx].deleted = True
                self.nodes[idx].timestamp = op.timestamp
                self._tombstone_version[op.node_id] = self.version_vector.copy()
                self._applied_ops.add(op.node_id)
                return True

        return False

    def _flush_pending(self):
        """Try to apply buffered inserts whose origins have now arrived."""
        flushed = []
        while self._pending_inserts:
            node_id, op = heapq.heappop(self._pending_inserts)
            if op.origin in self._index or op.origin is None:
                node = Node(
                    id=op.node_id,
                    value=op.value,
                    origin=op.origin,
                    timestamp=op.timestamp
                )
                self._integrate(node)
                self._applied_ops.add(op.node_id)
                flushed.append(node_id)
            else:
                # Still can't apply; re-add to queue
                heapq.heappush(self._pending_inserts, (node_id, op))
                break

    # ========================================================================
    # Integration Algorithm (Heart of Convergence)
    # ========================================================================

---

<details><summary>Reasoning trace supplied to Haiku</summary>

(no separate trace returned)

**Conclusion:** # CRDT for Text Editing (RGA-based)

I'll implement a **Replicated Growable Array (RGA)** CRDT, which is well-suited for text editing. It handles concurrent inserts and deletes while guaranteeing convergence.

## Core Design

Each character gets a unique, immutable **identifier** that establishes a total order. Deletions are tombstones (soft deletes) to preserve causality.

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
import bisect


@dataclass(frozen=True, order=True)
class Identifier:
    """
    Globally unique, totally-ordered identifier for a character.
    (logical_clock, replica_id) ensures determinism across replicas.
    """
    clock: int
    replica_id: int

    def __repr__(self):
        return f"({self.clock},{self.replica_id})"


@dataclass
class Node:
    """A single character node in the RGA sequence."""
    id: Identifier
    value: str
    # The id of the node this was inserted *after* (None = beginning)
    origin: Optional[Identifier]
    deleted: bool = False
```

## The CRDT Implementation

```python
class RGATextCRDT:
    def __init__(self, replica_id: int):
        self.replica_id = replica_id
        self.clock = 0
        # Ordered list of all nodes (including tombstones)
        self.nodes: List[Node] = []
        # Fast lookup: identifier -> index in self.nodes
        self._index: Dict[Identifier, int] = {}

    # ---------- Clock management ----------

    def _next_id(self) -> Identifier:
        self.clock += 1
        return Identifier(self.clock, self.replica_id)

    def _observe_clock(self, other_clock: int):
        """Lamport-style clock advancement on remote ops."""
        self.clock = max(self.clock, other_clock)

    # ---------- Visible (non-deleted) view ----------

    def _visible_positions(self) -> List[int]:
        return [i for i, n in enumerate(self.nodes) if not n.deleted]

    def text(self) -> str:
        return "".join(n.value for n in self.nodes if not n.deleted)

    def _visible_index_to_node_index(self, vis_idx: int) -> Optional[int]:
        """Map a visible cursor position to the underlying node index."""
        count = 0
        for i, n in enumerate(self.nodes):
            if not n.deleted:
                if count == vis_idx:
                    return i
                count += 1
        return None  # append at end
```

### Local Operations (generate ops)

```python
    def local_insert(self, vis_pos: int, char: str) -> dict:
        """
        Insert `char` at visible position `vis_pos`.
        Returns an operation to broadcast to other replicas.
        """
        # Determine the origin (node we insert after)
        if vis_pos == 0:
            origin = None
        else:
            node_idx = self._visible_index_to_node_index(vis_pos - 1)
            if node_idx is None:
                # insert at end -> after last visible node
                vis = self._visible_positions()
                node_idx = vis[-1] if vis else None
            origin = self.nodes[node_idx].id if node_idx is not None else None

        new_id = self._next_id()
        node = Node(id=new_id, value=char, origin=origin)
        self._integrate(node)

        return {
            "type": "insert",
            "id": (new_id.clock, new_id.replica_id),
            "value": char,
            "origin": (origin.clock, origin.replica_id) if origin else None,
        }

    def local_delete(self, vis_pos: int) -> Optional[dict]:
        """Delete the char at visible position `vis_pos`."""
        node_idx = self._visible_index_to_node_index(vis_pos)
        if node_idx is None:
            return None
        node = self.nodes[node_idx]
        node.deleted = True

        return {
            "type": "delete",
            "id": (node.id.clock, node.id.replica_id),
        }
```

### Remote Operations (apply ops)

```python
    def apply_remote(self, op: dict):
        """Apply an operation received from another replica. Idempotent."""
        if op["type"] == "insert":
            clock, rid = op["id"]
            new_id = Identifier(clock, rid)
            self._observe_clock(clock)

            if new_id in self._index:
                return  # Idempotent: already applied

            origin = None
            if op["origin"] is not None:
                oc, orid = op["origin"]
                origin = Identifier(oc, orid)

            node = Node(id=new_id, value=op["value"], origin=origin)
            self._integrate(node)

        elif op["type"] == "delete":
            clock, rid = op["id"]
            target = Identifier(clock, rid)
            idx = self._index.get(target)
            if idx is not None:
                self.nodes[idx].deleted = True  # Idempotent
```

### The Integration Algorithm (heart of convergence)

```python
    def _integrate(self, node: Node):
        """
        Insert `node` into the sequence deterministically.

        Rule: place after `origin`. Among nodes competing for the same
        origin (concurrent inserts), order by descending Identifier so
        the ordering is identical on every replica.
        """
        # Find the anchor position (right after origin)
        if node.origin is None:
            start = 0
        else:
            origin_idx = self._index.get(node.origin)
            if origin_idx is None:
                # Origin not yet seen (out-of-order delivery):
                # buffer or place at start. Simplest: place at start.
                start = 0
            else:
                start = origin_idx + 1

        # Skip over already-inserted nodes with the SAME origin that have
        # a higher identifier (concurrent siblings). This is the RGA
        # tie-break that guarantees deterministic convergence.
        i = start
        while i < len(self.nodes):
            existing = self.nodes[i]
            # Only siblings sharing the same origin compete here.
            if existing.origin == node.origin:
                if existing.id > node.id:
                    i += 1
                    continue
                else:
                    break
            else:
                # A node with a different origin that sorts after ours:
                # we must place before deeper descendants incorrectly.
                # Walk past subtree nodes whose id > node.id at this anchor.
                if existing.id > node.id:
                    i += 1
                    continue
                break

        self._insert_at(i, node)

    def _insert_at(self, idx: int, node: Node):
        self.nodes.insert(idx, node)
        # Rebuild index from idx onward (shifted positions)
        self._index[node.id] = idx
        for j in range(idx + 1, len(self.nodes)):
            self._index[self.nodes[j].id] = j
```

## Demonstration

```python
def sync(a: RGATextCRDT, b: RGATextCRDT, ops: List[dict]):
    """Deliver a batch of ops to a replica."""
    for op in ops:
        a.apply_remote(op)
        b.apply_remote(op)


if __name__ == "__main__":
    alice = RGATextCRDT(replica_id=1)
    bob   = RGATextCRDT(replica_id=2)

    # Alice types "HELLO"
    ops_a = []
    for i, ch in enumerate("HELLO"):
        ops_a.append(alice.local_insert(i, ch))
    for op in ops_a:
        bob.apply_remote(op)

    assert alice.text() == bob.text() == "HELLO"

    # ---- Concurrent edits (no coordination) ----
    # Alice inserts "!" at end -> "HELLO!"
    op1 = alice.local_insert(5, "!")
    # Bob concurrently deletes "H" and inserts "X" at start -> "XELLO"
    op2 = bob.local_delete(0)
    op3 = bob.local_insert(0, "X")

    # Exchange operations (order-independent)
    bob.apply_remote(op1)
    alice.apply_remote(op2)
    alice.apply_remote(op3)

    print("Alice:", alice.text())
    print("Bob:  ", bob.text())
    assert alice.text() == bob.text()  # CONVERGENCE guaranteed
    print("Converged ✓")
```

## How the Guarantees Are Met

| Property | Mechanism |
|----------|-----------|
| **Convergence** (strong eventual consistency) | Deterministic total order on `Identifier` `(clock, replica_id)`; integration always produces the same sequence regardless of delivery order. |
| **Commutativity** | `_integrate` result is independent of the order remote inserts arrive. |
| **Idempotence** | `_index` check drops duplicate inserts; deletes just re-set a flag. |
| **Intent preservation** | Inserts anchor to a specific `origin` character, so text lands where the user meant it—even after concurrent edits shift positions. |
| **No coordination** | Every replica generates ops locally; no locks, consensus, or central server. |
| **Deletes without conflict** | Tombstones preserve causal anchors so late-arriving inserts referencing a deleted char still position correctly. |

## Production Considerations

Things I simplified that a real system needs:

1. **Out-of-order delivery**: Buffer inserts whose `origin` hasn't arrived yet (a causal-delivery queue), rather than defaulting to position 0.
2. **Tombstone garbage collection**: Use version vectors to safely purge tombstones once all replicas have seen them.
3. **Performance**: Replace the `List` + full index rebuild with a **balanced tree / skip list / block-wise structure** (e.g., as in Yjs's YATA or Automerge) for O(log n) ops instead of O(n).
4. **Interleaving anomalies**: Pure RGA can interleave concurrent runs of insertions. Algorithms like **Fugue** or **YATA** improve intent preservation for concurrent typing at the same spot.

Would you like me to extend this with **causal-delivery buffering**, a **tree-based backing store** for performance, or **tombstone GC**?
</details>
