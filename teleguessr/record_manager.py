from teleguessr.models import Records
from pathlib import Path
from datetime import datetime
import json


class RecordManager:
    def __init__(self, data_dir: Path):
        self.records_file = data_dir / "records" / "records.json"

    def get_records(self) -> dict[str, Records]:
        with open(self.records_file, "r") as f:
            records_data = json.load(f)

        data = {key: Records(**value) for key, value in records_data.items()}
        # Sort the records by net wins, then gross wins, then most recent net win, then most recent gross win
        data = dict(
            sorted(
                data.items(),
                key=lambda item: (
                    item[1].net_wins,
                    item[1].gross_wins,
                    item[1].most_recent_net_win or datetime.min.date(),
                    item[1].most_recent_gross_win or datetime.min.date(),
                ),
                reverse=True,
            )
        )
        return data

    def _save_records(self, records: dict[str, Records]) -> None:
        with open(self.records_file, "w") as f:
            json.dump(
                {key: value.model_dump() for key, value in records.items()}, f, indent=4
            )

    def update_records(
        self, net_winner: str, gross_winner: str, date: datetime = None
    ) -> dict[str, Records]:
        if date is None:
            date = datetime.utcnow().date()

        records = self.get_records()
        if net_winner == gross_winner:
            record = records.get(net_winner, Records(net_wins=0, gross_wins=0))
            record.net_wins += 1
            record.gross_wins += 1
            record.most_recent_net_win = date
            record.most_recent_gross_win = date
            records[net_winner] = record
        else:
            gross_record = records.get(gross_winner, Records(net_wins=0, gross_wins=0))
            net_record = records.get(net_winner, Records(net_wins=0, gross_wins=0))

            net_record.net_wins += 1
            net_record.most_recent_net_win = date
            gross_record.gross_wins += 1
            gross_record.most_recent_gross_win = date

            records[net_winner] = net_record
            records[gross_winner] = gross_record

        self._save_records(records)
        return records
