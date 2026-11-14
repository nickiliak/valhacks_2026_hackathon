"""Frozen chronological periods from plan/05_validation_and_splits.md."""

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class Period:
    """Half-open interval [start, end), based on arrival_date."""

    start: str
    end: str

    def select(self, rows: pd.DataFrame) -> pd.DataFrame:
        dates = pd.to_datetime(rows["arrival_date"])
        return rows.loc[(dates >= self.start) & (dates < self.end)].copy()


@dataclass(frozen=True)
class ChronologicalSplit:
    name: str
    train: Period
    internal_validation: Period
    calibration: Period
    replay: Period
    tuning: Period | None = None
    confirmation: Period | None = None

    def training_parts(self, rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        train = self.train.select(rows)
        dates = pd.to_datetime(train.arrival_date)
        fit = train.loc[dates < self.internal_validation.start].copy()
        validation = self.internal_validation.select(train)
        return fit, validation

    def to_dict(self) -> dict:
        return asdict(self)


SPLITS = {
    "S2": ChronologicalSplit(
        "S2", Period("2015-07-01", "2016-04-01"),
        Period("2016-02-01", "2016-04-01"),
        Period("2016-04-01", "2016-07-01"),
        Period("2016-07-01", "2017-01-01"),
        Period("2016-07-01", "2016-10-01"),
        Period("2016-10-01", "2017-01-01"),
    ),
    "S1": ChronologicalSplit(
        "S1", Period("2015-07-01", "2015-11-01"),
        Period("2015-09-01", "2015-11-01"),
        Period("2015-11-01", "2016-01-01"),
        Period("2016-01-01", "2017-01-01"),
    ),
    "Final": ChronologicalSplit(
        "Final", Period("2015-07-01", "2016-10-01"),
        Period("2016-08-01", "2016-10-01"),
        Period("2016-10-01", "2017-01-01"),
        Period("2017-01-01", "2018-01-01"),
    ),
}


def get_split(name: str = "S2") -> ChronologicalSplit:
    try:
        return SPLITS[name]
    except KeyError:
        raise ValueError(f"Unknown split {name!r}; choose from {list(SPLITS)}") from None


def replay_population(rows: pd.DataFrame, period: Period) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return commitments and requests, each in official global decision order."""
    population = period.select(rows)
    population["booking_date"] = pd.to_datetime(population.booking_date)
    population["arrival_date"] = pd.to_datetime(population.arrival_date)
    population = population.sort_values(["booking_date", "booking_id"], kind="stable")
    prior = pd.to_datetime(population.booking_date) < period.start
    return population.loc[prior].copy(), population.loc[~prior].copy()
