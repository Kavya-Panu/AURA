"""
memory/memory_events.py
=======================
Mapping of Memory events onto the core RobotEvent bus vocabulary. The Memory
Manager publishes ONLY these. It does not subscribe to or drive any other
module; the Brain Manager calls the Memory Manager's API directly (never the
storage), and other modules can listen to these events if they wish.
"""
from __future__ import annotations

from core.constants import RobotEvent

MEMORY_STORED = RobotEvent.MEMORY_STORED
MEMORY_RETRIEVED = RobotEvent.MEMORY_RETRIEVED
MEMORY_UPDATED = RobotEvent.MEMORY_UPDATED
MEMORY_DELETED = RobotEvent.MEMORY_DELETED
MEMORY_SEARCHED = RobotEvent.MEMORY_SEARCHED           # "MEMORY_FOUND" in spec
MEMORY_SUMMARIZED = RobotEvent.MEMORY_SUMMARIZED
MEMORY_FORGOTTEN = RobotEvent.MEMORY_FORGOTTEN
MEMORY_EXPIRED = RobotEvent.MEMORY_EXPIRED
MEMORY_CLEANUP_COMPLETED = RobotEvent.MEMORY_CLEANUP_COMPLETED
