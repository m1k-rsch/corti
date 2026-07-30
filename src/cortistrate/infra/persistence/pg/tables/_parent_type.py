"""Shared parent-type enum for PG table schemas."""

import enum


class ParentType(enum.Enum):
    MEMCELL = "memcell"
    CLUSTER = "cluster"
