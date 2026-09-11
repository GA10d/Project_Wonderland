"""数据逻辑示例：Blob 邻接、占地、入口预留；无渲染与寻路依赖。"""

from dataclasses import dataclass


# 本例位序不是任何图集的索引约定。
N, E, S, W, NE, SE, SW, NW = (1 << i for i in range(8))
NEIGHBORS = (
    (0, -1, N), (1, 0, E), (0, 1, S), (-1, 0, W),
    (1, -1, NE), (1, 1, SE), (-1, 1, SW), (-1, -1, NW),
)


def normalize_mask(mask):
    """两条相邻直边均连接时，对角关系才参与 Blob 选图。"""
    for diagonal, side_a, side_b in (
        (NE, N, E), (SE, S, E), (SW, S, W), (NW, N, W)
    ):
        if not (mask & side_a and mask & side_b):
            mask &= ~diagonal
    return mask


def blob_mask(terrain, x, y):
    """地图外视为不连接；terrain 要求为非空矩形二维网格。"""
    height, width = len(terrain), len(terrain[0])
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError("当前格超出地图边界")
    current = terrain[y][x]
    mask = 0
    for dx, dy, bit in NEIGHBORS:
        nx, ny = x + dx, y + dy
        if (0 <= nx < width and 0 <= ny < height
                and terrain[ny][nx] == current):
            mask |= bit
    return normalize_mask(mask)


@dataclass(frozen=True)
class ObjectSpec:
    name: str
    footprint: frozenset
    access: frozenset  # 建筑外部的入口与通路预留，不能与 footprint 相交
    allowed_terrain: frozenset


class PlacementMap:
    """单线程示例；预留区也要求合法地形及同高，但不检查路径可达性。"""

    def __init__(self, terrain, elevation):
        if not terrain or not terrain[0]:
            raise ValueError("地图不能为空")
        self.width, self.height = len(terrain[0]), len(terrain)
        if any(len(row) != self.width for row in terrain):
            raise ValueError("terrain 必须是矩形")
        if (len(elevation) != self.height
                or any(len(row) != self.width for row in elevation)):
            raise ValueError("高度网格尺寸必须匹配")
        self.terrain = terrain
        self.elevation = elevation
        self.occupied = set()
        self.reserved = set()
        self.objects = []

    def check(self, spec, origin):
        if not spec.footprint or spec.footprint & spec.access:
            return False, "对象占地定义无效"
        ox, oy = origin
        footprint = {(ox + x, oy + y) for x, y in spec.footprint}
        access = {(ox + x, oy + y) for x, y in spec.access}
        cells = footprint | access
        if any(not (0 <= x < self.width and 0 <= y < self.height)
               for x, y in cells):
            return False, "占地或入口超出地图"
        if any(self.terrain[y][x] not in spec.allowed_terrain
               for x, y in cells):
            return False, "地形不支持放置或通行"
        if len({self.elevation[y][x] for x, y in cells}) != 1:
            return False, "占地与入口不是同一高度"
        if footprint & (self.occupied | self.reserved):
            return False, "占地冲突或堵住预留通路"
        if access & self.occupied:
            return False, "入口被已有对象堵住"
        # 允许两个建筑共享通路预留区。
        return True, "局部检查通过；实际游戏还需按玩法检查路径可达性"

    def place(self, spec, origin):
        ok, reason = self.check(spec, origin)
        if not ok:
            return False, reason
        ox, oy = origin
        # 所有检查完成后才修改状态。
        self.occupied.update((ox + x, oy + y) for x, y in spec.footprint)
        self.reserved.update((ox + x, oy + y) for x, y in spec.access)
        self.objects.append({"type": spec.name, "origin": origin})
        return True, reason


def main():
    masks = {normalize_mask(mask) for mask in range(256)}
    assert len(masks) == 47
    assert blob_mask([list("...") , list(".##"), list(".##")], 1, 1) == E | S | SE
    assert blob_mask([list(".##"), list("###"), list("###")], 1, 1) == 255 - NW
    assert blob_mask([["#"]], 0, 0) == 0
    assert normalize_mask(NE) == 0  # 仅对角接触不能产生直边连接
    print(f"256 种邻域组合 → {len(masks)} 种有效 Blob 形态")

    terrain = [list(row) for row in (
        "............",
        ".##########.",
        ".##########.",
        ".##########.",
        ".##########.",
        ".##########.",
        ".##########.",
        "............",
    )]
    world = PlacementMap(terrain, [[0] * 12 for _ in range(8)])
    house = ObjectSpec(
        "cottage", frozenset((x, y) for y in range(3) for x in range(4)),
        frozenset({(1, 3), (1, 4)}), frozenset({"#"}),
    )
    tree = ObjectSpec("tree", frozenset({(0, 0)}), frozenset(), frozenset({"#"}))

    result = world.place(house, (2, 1))
    assert result[0]
    print("放置房屋：", result)
    before = (set(world.occupied), set(world.reserved), list(world.objects))
    result = world.place(tree, (3, 4))
    assert not result[0]
    assert before == (world.occupied, world.reserved, world.objects)
    print("在门前放树：", result)
    assert not world.place(tree, (2, 1))[0]  # 房屋占地
    assert not world.place(tree, (0, 0))[0]  # 水域
    assert not world.place(house, (10, 6))[0]  # 越界
    world.elevation[2][8] = 1
    assert not world.check(house, (7, 1))[0]  # 高度不一致
    world.elevation[2][8] = 0
    assert world.place(tree, (8, 2))[0]

    print("\n地图：. 水，# 草，B 对象占地，+ 通路预留")
    for y, row in enumerate(terrain):
        print("".join("B" if (x, y) in world.occupied else
                      "+" if (x, y) in world.reserved else tile
                      for x, tile in enumerate(row)))
    print("\n核心检查通过。mask → 素材映射、渲染、碰撞和寻路需另行接入。")


if __name__ == "__main__":
    main()
