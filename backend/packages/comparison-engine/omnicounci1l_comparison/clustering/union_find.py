"""Union-Find (Disjoint Set) data structure for clustering."""

from __future__ import annotations


class UnionFind:
    """Union-Find with path compression and union by rank."""

    def __init__(self, n: int) -> None:
        self._parent = list(range(n))
        self._rank = [0] * n
        self._count = n

    def find(self, x: int) -> int:
        """Find root of x with path compression."""
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, x: int, y: int) -> bool:
        """Union two sets. Returns True if they were in different sets."""
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return False

        if self._rank[root_x] < self._rank[root_y]:
            root_x, root_y = root_y, root_x

        self._parent[root_y] = root_x
        if self._rank[root_x] == self._rank[root_y]:
            self._rank[root_x] += 1

        self._count -= 1
        return True

    def connected(self, x: int, y: int) -> bool:
        """Check if x and y are in the same set."""
        return self.find(x) == self.find(y)

    @property
    def count(self) -> int:
        """Number of distinct sets."""
        return self._count

    def components(self) -> dict[int, list[int]]:
        """Get all connected components as {root: [members]}."""
        result: dict[int, list[int]] = {}
        for i in range(len(self._parent)):
            root = self.find(i)
            if root not in result:
                result[root] = []
            result[root].append(i)
        return result
