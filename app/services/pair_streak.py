"""Pair streaks: consecutive days on which *both* friends sent each other a snap.

Pure, so the rules are easy to test. A missed day resets the streak (no
freezes or grace day, by the client's decision).
"""

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PairStreak:
    count: int
    sent_today: bool  # I have sent them a snap today
    they_sent_today: bool  # they have sent me one today

    @property
    def complete_today(self) -> bool:
        return self.sent_today and self.they_sent_today

    @property
    def at_risk(self) -> bool:
        """A running streak that needs a snap from someone today to survive."""
        return self.count > 0 and not self.complete_today


def pair_streak(mine: set[date], theirs: set[date], today: date) -> PairStreak:
    """[mine]: days I sent them a snap. [theirs]: days they sent me one."""
    both = mine & theirs
    # Today may still be unfinished, so a run that ended yesterday is alive.
    cursor = today if today in both else today - timedelta(days=1)
    count = 0
    while cursor in both:
        count += 1
        cursor -= timedelta(days=1)
    return PairStreak(count, today in mine, today in theirs)
