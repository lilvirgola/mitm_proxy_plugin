"""
Seeded random number generator for deterministic behavior in tests.
Why having a class for this? cos' i this this allow to easily swap out the RNG implementation if needed, and it encapsulates the seeding logic in one place...
Anyway, this is a more "clean code" approach in my opinion, and it makes the code more readable and maintainable.
"""
import random

class SeededRNG:
    def __init__(self):
        self._rng = random.Random()

    def set_seed(self, seed: int):
        self._rng.seed(seed)

    def shuffle(self, lst: list):
        self._rng.shuffle(lst)