from dataclasses import dataclass, field
import csv

Position = tuple[int, int]

STD_MAP_SIZE = (750, 750)

# 可用于识别的POI建筑类型列表前缀
POI_CONSTRUCTS = [
    30, 32, 34, 37, 38, 40, 41, 
    50, 51, 52, 5358, 5359, 5367, 5368,
]
# 大空洞地下区域坐标
TGH_UNDERGROUND_COORDS = [1160, 1159, 1107, 1110, 1153, 1175, 1174]

@dataclass
class Construct:
    type: int
    is_display: bool
    is_underground: bool = False
    pos_index: int = None
    pos: Position = None

@dataclass
class MapPattern:
    id: int
    nightlord: int
    earth_shifting: int
    day1_boss: int
    day1_extra_boss: int
    day1_pos: Position
    day2_boss: int
    day2_extra_boss: int
    day2_pos: Position
    day2_pos_idx: int
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
    tgh_pos_dict: dict[int, Position]
    patterns: list[MapPattern]

    all_earth_shiftings: set[int]
    all_nightlords: set[int]

    all_poi_pos: dict[tuple[int, int], set[Position]]
    all_poi_construct_type: dict[tuple[int, int], set[int]]
    possible_poi_types: dict[tuple[int, int, Position], set[int]]

    def get_name(self, map_id: int) -> str:
        return self.name_dict.get(map_id)


def original_to_std_coord(p: tuple[float, float]) -> Position:
    """
    游戏原始坐标转换为程序标准坐标
    """
    return (
        int((p[0] - 907.5537109) / 6.045 + 127.26920918617023),
        int((p[1] - 1571.031006) / 6.045 + 242.71771372340424),
    )

def tgh_original_to_std_coord(p: tuple[float, float]) -> Position:
    """
    大空洞游戏原始坐标转换为程序标准坐标
    """
    return (
        int(((p[0] * 1.0186 - 306 - 907.5537109) / 6.045 + 127.26920918617023) * 1.23 - 6),
        int(((p[1] * 1.0186 - 260 - 1571.031006) / 6.045 + 242.71771372340424) * 1.23 - 55),
    )


def load_map_info(
    map_patterns_csv_path: str,
    constructs_csv_path: str,
    names_csv_path: str,
    positions_csv_path: str,
):
    with open(names_csv_path, 'r', encoding='utf-8') as f:
        f.readline()
        reader = csv.reader(f)
        name_dict = {int(row[0]): row[1] for row in reader}

    with open(positions_csv_path, 'r', encoding='utf-8') as f:
        f.readline()
        reader = csv.reader(f)
        pos_dict, tgh_pos_dict = {}, {}
        for row in reader:
            x, y = float(row[7]), float(row[8])
            pos_dict[int(row[0])] = original_to_std_coord((x, y))
            tgh_pos_dict[int(row[0])] = tgh_original_to_std_coord((x, y))
    
    with open(constructs_csv_path, 'r', encoding='utf-8') as f:
        f.readline()
        reader = csv.reader(f)
        map_construct_dict: dict[int, list[Construct]] = {}
        for row in reader:
            map_id = int(row[1])
            construct = Construct(
                type=int(row[2]),
                pos_index=int(row[4]),
                is_display=(row[3] == '1'),
                is_underground=(int(row[4]) in TGH_UNDERGROUND_COORDS),
            )
            map_construct_dict.setdefault(map_id, []).append(construct)

    with open(map_patterns_csv_path, 'r', encoding='utf-8') as f:
        f.readline()
        reader = csv.reader(f)
        patterns: list[MapPattern] = []
        for row in reader:
            pattern_pos_dict = pos_dict if int(row[2]) != 4 else tgh_pos_dict
            patterns.append(MapPattern(
                id=int(row[0]),
                nightlord=int(row[1]),
                earth_shifting=int(row[2]),
                treasure=int(row[4]),
                event_value=int(row[5]),
                event_flag=int(row[6]),
                evpat_value=int(row[7]),
                evpat_flag=int(row[8]),
                rot_rew=int(row[9]),
                day1_boss=int(row[10]),
                day1_pos=pattern_pos_dict[int(row[11])],
                day2_boss=int(row[12]),
                day2_pos=pattern_pos_dict[int(row[13])],
                day2_pos_idx=int(row[13]),
                day1_extra_boss=int(row[14]),
                day2_extra_boss=int(row[15]),
                pos_constructions={}
            ))
            for c in map_construct_dict.get(int(row[0]), []):
                c.pos = pattern_pos_dict[c.pos_index]
                patterns[-1].pos_constructions[c.pos] = c
    
    # 收集所有可能的POI建筑位置和类型
    all_earth_shiftings: set[int] = set()
    all_nightlords: set[int] = set()
    all_poi_pos: dict[tuple[int, int], set[Position]] = {} # [earth_shifting, nightlord] -> set[pos]
    all_poi_construct_type: dict[tuple[int, int], set[int]] = {}  # [earth_shifting, nightlord] -> set[type]
    possible_poi_types: dict[tuple[int, int, Position], set[int]] = {}  # [earth_shifting, nightlord, pos] -> set[type]
    for pattern in patterns:
        es, nightlord = pattern.earth_shifting, pattern.nightlord
        all_earth_shiftings.add(es)
        all_nightlords.add(nightlord)
        for construct in pattern.pos_constructions.values():
            if any(str(construct.type).startswith(str(ctype)) for ctype in POI_CONSTRUCTS):
                if pattern.earth_shifting == 4 and construct.is_underground:
                    continue  # 大空洞地下建筑不纳入POI
                all_poi_pos.setdefault((es, nightlord), set()).add(construct.pos)
                all_poi_construct_type.setdefault((es, nightlord), set()).add(construct.type)
                possible_poi_types.setdefault((es, nightlord, construct.pos), set()).add(construct.type)

    # 对某个poi位置，判断该位置是否在一个地图中没有建筑，加入0表示无建筑
    for es, nightlord, pos in possible_poi_types.keys():
        all_poi_construct_type[(es, nightlord)].add(0)
        for pattern in patterns:
            if pattern.earth_shifting == es and pattern.nightlord == nightlord:
                if pos not in pattern.pos_constructions:
                    possible_poi_types[(es, nightlord, pos)].add(0)

    return MapInfo(
        name_dict=name_dict,
        pos_dict=pos_dict,
        tgh_pos_dict=tgh_pos_dict,
        patterns=patterns,
        all_earth_shiftings=all_earth_shiftings,
        all_nightlords=all_nightlords,
        all_poi_pos=all_poi_pos,
        all_poi_construct_type=all_poi_construct_type,
        possible_poi_types=possible_poi_types,
    )