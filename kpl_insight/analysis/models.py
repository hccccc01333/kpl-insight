# -*- coding: utf-8 -*-
"""Series analysis data model.

All orientations are explicit:
  - Game.team1 / Game.team2 are the battle-side camps (blue/red in the source).
  - Game.winner is a team name, never "camp 1".
  - Frame.p / Frame.gold_diff are from Game.team1's perspective.
  - Series.side_of(team) maps a series team to the battle-side ordinal.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Frame:
    minute: float
    p: float | None
    gold_diff: float
    kills: list[int]
    towers: list[int]
    objectives: list[list[int]]
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class Game:
    battle_id: str
    seq: int
    team1: str
    team2: str
    winner: str
    duration: float
    kills: list[int]
    gold: list[int]
    bp: list[list]
    players: list[dict]
    frames: list[Frame]
    events: list[dict]
    warnings: list[str] = field(default_factory=list)
    frames_total: int = 0
    quarantined_frames: int = 0

    def side_of(self, team: str) -> int:
        if team == self.team1:
            return 1
        if team == self.team2:
            return 2
        raise ValueError(f"{team!r} is not in game {self.battle_id}")

    def opposite(self, team: str) -> str:
        return self.team2 if team == self.team1 else self.team1

    def p_for(self, frame: Frame, team: str) -> float | None:
        if frame.p is None:
            return None
        return frame.p if team == self.team1 else 1.0 - frame.p

    def gold_for(self, frame: Frame, team: str) -> float | None:
        if frame.gold_diff is None:
            return None
        return frame.gold_diff if team == self.team1 else -frame.gold_diff

    def winner_is_side1(self) -> bool:
        return self.winner == self.team1

    def final_frame(self) -> Frame | None:
        return self.frames[-1] if self.frames else None

    def early_frame(self, minute: float = 8.0) -> Frame | None:
        """First frame at/after the target; fall back to the last valid frame.

        KPL snapshots are sparse (often 7.6′ then 8.9′). Using the first frame
        at/after 8′ avoids calling the 7.6′ state the "8-minute" state.
        """
        if not self.frames:
            return None
        after = [f for f in self.frames if f.minute >= minute]
        return min(after, key=lambda f: f.minute) if after else self.frames[-1]


@dataclass
class Series:
    match_id: str
    date: str
    league_id: str
    league_name: str
    stage: str
    bo: int
    team1: str
    team2: str
    score1: int
    score2: int
    games: list[Game]
    warnings: list[str] = field(default_factory=list)
    source: str = ""

    def side_of(self, game: Game, team: str) -> int:
        return game.side_of(team)

    def score(self) -> tuple[int, int]:
        return self.score1, self.score2
