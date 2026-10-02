import datetime
from types import SimpleNamespace

from cogs.event import (
    get_attendance_stats,
    make_bar,
    summarize_events,
    summarize_games,
)


def _record(event_id, user_id, attended, voted_for_winner=False, day=None, game=None):
    return SimpleNamespace(
        event_id=event_id,
        user_id=user_id,
        attended=attended,
        voted_for_winner=voted_for_winner,
        timestamp=datetime.datetime(2026, 1, day or event_id),
        winning_game=game,
    )


RECORDS = [
    _record(1, 1, True, game="Northstar"),
    _record(1, 2, True, game="Northstar"),
    _record(2, 1, True, game="Titanfall"),
    _record(2, 2, False, voted_for_winner=True, game="Titanfall"),
    _record(3, 2, True, game="northstar"),
    _record(3, 3, True),
    # A manual correction added later shouldn't move the event date
    _record(3, 1, True, day=20),
    _record(4, 1, True, game="Titanfall"),
]


def test_summarize_events() -> None:
    events = summarize_events(reversed(RECORDS))

    assert [e.event_id for e in events] == [1, 2, 3, 4]
    assert [len(e.attendees) for e in events] == [2, 1, 3, 1]
    assert events[1].no_shows == {2}
    assert events[2].date == datetime.datetime(2026, 1, 3)
    # Rows added without a game pick it up from the rest of the event
    assert [e.game for e in events] == [
        "Northstar",
        "Titanfall",
        "northstar",
        "Titanfall",
    ]


def test_attendance_stats() -> None:
    events = summarize_events(RECORDS)

    one = get_attendance_stats(events, 1)
    assert (one.attended, one.eligible, one.no_shows) == (4, 4, 0)
    assert (one.current_streak, one.longest_streak, one.rank) == (4, 4, 1)
    assert one.favorite_game == "Northstar"

    two = get_attendance_stats(events, 2)
    assert (two.attended, two.no_shows, two.current_streak) == (2, 1, 0)
    assert two.rank == 2

    # Newcomers are only measured against events since they joined
    three = get_attendance_stats(events, 3)
    assert (three.attended, three.eligible, three.rate) == (1, 2, 50.0)
    assert three.ranked_users == 3

    assert get_attendance_stats(events, 99) is None


def test_make_bar() -> None:
    assert make_bar(5, 10, width=10) == "█" * 5
    assert make_bar(0, 0) == ""


def test_summarize_games() -> None:
    games = summarize_games(summarize_events(RECORDS))

    # Casing differences are the same game
    assert [(g.name, g.played, g.attendance) for g in games] == [
        ("Northstar", 2, 5),
        ("Titanfall", 2, 2),
    ]
    assert games[0].average == 2.5
    assert games[1].no_shows == 1
