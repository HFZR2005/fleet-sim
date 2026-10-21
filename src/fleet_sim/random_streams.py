"""Independent random streams from one master seed.

A stream is fixed by the master seed and its name. Asking for another name
does not move an existing stream, so a later random feature can be added
without changing homes that were already drawn.
"""

import hashlib

import numpy as np


class RandomStreams:
    """NumPy generators keyed by name, all derived from one seed."""

    def __init__(self, seed: int) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise TypeError(f"seed must be an int (got {seed!r})")
        if seed < 0:
            raise ValueError(f"seed must be at least 0 (got {seed})")
        self._seed = seed
        self._generators: dict[str, np.random.Generator] = {}

    def generator(self, name: str) -> np.random.Generator:
        """Return the generator for ``name``, creating it on first use.

        The same seed and name always start at the same draw. The sequence
        does not depend on which other names have been requested.
        """
        if name == "":
            raise ValueError("stream name must not be empty")
        existing = self._generators.get(name)
        if existing is not None:
            return existing
        created = np.random.default_rng(
            np.random.SeedSequence([self._seed, *_name_entropy(name)])
        )
        self._generators[name] = created
        return created


def _name_entropy(name: str) -> list[int]:
    """Stable integers from ``name``. ``hash`` is salted per process."""
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return [
        int.from_bytes(digest[index : index + 4], "little") for index in range(0, 16, 4)
    ]
