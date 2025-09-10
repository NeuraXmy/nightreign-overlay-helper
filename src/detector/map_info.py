from dataclasses import dataclass
import csv

Position = tuple[int, int]

STD_MAP_SIZE = (750, 750)
POI_CONSTRUCTS = [30, 32, 34, 37, 38, 40, 41]


@dataclass
class Construct:
    type: int
    pos: Position
    is_display: bool


@dataclass
class MapPattern:
    id: int
    nightlord: int
    earth_shifting: int
    start_pos: Position
    day1_boss: int
    day1_extra_boss: int
    day1_pos: Position
    day2_boss: int
    day2_extra_boss: int
    day2_pos: Position
    treasure: int
    rot_rew: int
    event_value: int
    event_flag: int
    evpat_value: int
    evpat_flag: int
    pos_constructions: dict[Position, Construct]


@dataclass
class MapInfo:
    name_dict: dict[int, str]
    pos_dict: dict[int, Position]
    patterns: list[MapPattern]

    all_poi_pos: set[Position]
    all_poi_construct_type: set[int]

    def get_name(self, map_id: int) -> str:
        return self.name_dict.get(map_id)


def load_map_info(
    map_patterns_csv_path: str,
    constructs_csv_path: str,
    names_csv_path: str,
    positions_csv_path: str,
):
    with open(names_csv_path, "r", encoding="utf-8") as f:
        f.readline()
        reader = csv.reader(f)
        name_dict = {int(row[0]): row[1] for row in reader}

    with open(positions_csv_path, "r", encoding="utf-8") as f:
        f.readline()
        reader = csv.reader(f)
        pos_dict = {}
        for row in reader:
            x, y = float(row[7]), float(row[8])
            x = int((x - 907.5537109) / 6.045 + 127.26920918617023)
            y = int((y - 1571.031006) / 6.045 + 242.71771372340424)
            pos_dict[int(row[0])] = (x, y)

    with open(constructs_csv_path, "r", encoding="utf-8") as f:
        f.readline()
        reader = csv.reader(f)
        map_construct_dict: dict[int, list[Construct]] = {}
        all_poi_pos, all_poi_construct_type = set(), set()
        for row in reader:
            map_id = int(row[1])
            construct = Construct(
                type=int(row[2]),
                pos=pos_dict[int(row[4])],
                is_display=(row[3] == "1"),
            )
            map_construct_dict.setdefault(map_id, []).append(construct)
            if construct.type // 1000 in POI_CONSTRUCTS:
                all_poi_pos.add(construct.pos)
                all_poi_construct_type.add(construct.type)
        all_poi_construct_type.add(0)

    with open(map_patterns_csv_path, "r", encoding="utf-8") as f:
        f.readline()
        reader = csv.reader(f)
        patterns = []
        for row in reader:
            patterns.append(
                MapPattern(
                    id=int(row[0]),
                    nightlord=int(row[1]),
                    earth_shifting=int(row[2]),
                    start_pos=pos_dict[int(row[3])],
                    treasure=int(row[4]),
                    event_value=int(row[5]),
                    event_flag=int(row[6]),
                    evpat_value=int(row[7]),
                    evpat_flag=int(row[8]),
                    rot_rew=int(row[9]),
                    day1_boss=int(row[10]),
                    day1_pos=pos_dict[int(row[11])],
                    day2_boss=int(row[12]),
                    day2_pos=pos_dict[int(row[13])],
                    day1_extra_boss=int(row[14]),
                    day2_extra_boss=int(row[15]),
                    pos_constructions={
                        c.pos: c for c in map_construct_dict.get(int(row[0]), [])
                    },
                )
            )

    return MapInfo(
        name_dict=name_dict,
        pos_dict=pos_dict,
        patterns=patterns,
        all_poi_pos=all_poi_pos,
        all_poi_construct_type=all_poi_construct_type,
    )
