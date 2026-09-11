from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, deque
from pathlib import Path

from .catalog import normalized_mask
from .config import CELL
from .models import Asset, BuildingSpec, Entity, Placement, Portal, RoomSpec, Scene, SceneSpec, World

PLAYER_HALF = 9
PLAYER_HALF_Y = 6
COMPILER_VERSION = "0.1.3"


def intersects(a, b) -> bool:
    return a[0] < b[0] + b[2] and a[0] + a[2] > b[0] and a[1] < b[1] + b[3] and a[1] + a[3] > b[1]


def entity_rect(e: Entity, assets: dict[str, Asset]):
    c = assets[e.asset_id].collision
    return (e.x + c[0], e.y + c[1], c[2], c[3]) if c else None


def visual_rect(e: Entity, assets):
    a = assets[e.asset_id]
    return e.x - a.anchor[0], e.y - a.anchor[1], *a.size


def solid_rects(scene: Scene, assets):
    result = [r for e in scene.entities if (r := entity_rect(e, assets))]
    for y, row in enumerate(scene.terrain):
        for x, tile in enumerate(row):
            if tile in ("water", "wall"):
                result.append((x * CELL, y * CELL, CELL, CELL))
    return result


def can_stand(scene: Scene, assets, x: float, y: float, rects=None) -> bool:
    if not (PLAYER_HALF <= x <= scene.width * CELL - PLAYER_HALF
            and PLAYER_HALF_Y <= y <= scene.height * CELL - PLAYER_HALF_Y):
        return False
    feet = (x - PLAYER_HALF, y - PLAYER_HALF_Y, PLAYER_HALF * 2, PLAYER_HALF_Y * 2)
    return not any(intersects(feet, r) for r in (rects if rects is not None else solid_rects(scene, assets)))


def reachable_cells(scene: Scene, assets, start=None):
    """16px navigation grid, testing the full player's feet at centers and edges."""
    step = CELL // 2
    width, height = scene.width * 2, scene.height * 2
    rects = solid_rects(scene, assets)
    allowed = set()
    for y in range(height):
        for x in range(width):
            if can_stand(scene, assets, x * step + step / 2, y * step + step / 2, rects):
                allowed.add((x, y))
    px, py = start or scene.spawn
    seed = (int(px // step), int(py // step))
    if seed not in allowed:
        return set()
    queue, seen = deque([seed]), {seed}
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            if (nx, ny) not in allowed or (nx, ny) in seen:
                continue
            # Segment midpoint catches thin obstacles between navigation samples.
            if not can_stand(scene, assets, (x+nx+1)*step/2, (y+ny+1)*step/2, rects):
                continue
            seen.add((nx, ny)); queue.append((nx, ny))
    return seen


def validate_world(world: World) -> list[str]:
    errors = []
    for scene in world.scenes.values():
        if len(scene.terrain) != scene.height or any(len(row) != scene.width for row in scene.terrain):
            errors.append(f"{scene.id}: 地形尺寸错误"); continue
        if not can_stand(scene, world.assets, *scene.spawn):
            errors.append(f"{scene.id}: 出生点被阻挡")
        reachable = reachable_cells(scene, world.assets)
        for portal in scene.portals:
            if portal.target_scene not in world.scenes:
                errors.append(f"{portal.id}: 目标场景不存在"); continue
            target = world.scenes[portal.target_scene]
            if not can_stand(target, world.assets, *portal.target_spawn):
                errors.append(f"{portal.id}: 目标出生点被阻挡")
            if not any(intersects((x*16+7, y*16+7, 2, 2), portal.rect) for x, y in reachable):
                errors.append(f"{portal.id}: 门口不可达")
            if any(intersects((portal.target_spawn[0]-1, portal.target_spawn[1]-1, 2, 2), p.rect)
                   for p in target.portals):
                errors.append(f"{portal.id}: 目标出生点落在传送区内")
    return errors


def tile_mask(scene: Scene, x: int, y: int) -> int:
    kind, mask = scene.terrain[y][x], 0
    for dx, dy, bit in ((0,-1,1),(1,0,2),(0,1,4),(-1,0,8),(1,-1,16),(1,1,32),(-1,1,64),(-1,-1,128)):
        nx, ny = x+dx, y+dy
        if 0 <= nx < scene.width and 0 <= ny < scene.height and scene.terrain[ny][nx] == kind:
            mask |= bit
    return normalized_mask(mask)


def demo_spec() -> SceneSpec:
    return SceneSpec(title="风经过的小屋", summary="草木环绕的乡间木屋。走进屋内，探索温暖的生活空间。",
        biome="meadow", pond=True, buildings=[BuildingSpec(asset_id="house.country", name="风栖小屋", zone="center",
            interior=RoomSpec(name="温暖的起居室", furniture=[
                Placement(asset_id=aid, count=1, zone=zone) for aid, zone in [
                    ("furniture.bed","west"), ("furniture.cabinet","east"), ("furniture.fireplace","north"),
                    ("furniture.table","center"), ("furniture.chair","east"), ("furniture.plant","west"),
                    ("furniture.lamp","east")]]))],
        outdoors=[Placement(asset_id=aid, count=n, zone=zone) for aid,n,zone in [
            ("tree.oak",18,"scattered"),("tree.pine",12,"scattered"),("prop.well",1,"near_house"),
            ("prop.sign",1,"near_house"),("prop.rock",7,"scattered"),("prop.hay",4,"scattered")]],
        missing_assets=[], unsupported_requests=[])


ZONE = {"north":(.5,.28),"south":(.5,.75),"west":(.25,.52),"east":(.76,.52),"center":(.5,.52)}


class PlacementError(ValueError):
    def __init__(self,request,asset,placed,rejections):
        self.layout_details=dict(asset_id=asset.id,asset_name=asset.name,zone=request.zone,
                                 placed=placed,requested=request.count,rejections=dict(rejections))
        super().__init__(f"无法满足摆放数量：{asset.name[:32]}（区域 {request.zone}，已放 {placed}/{request.count}）。")


def outdoor_candidates(request,scene,assets,buildings,rng,index=0):
    """Try the preferred cluster, then search the full requested region once.

    A large building can cover the entire preferred cluster. Changing the seed
    cannot help unless candidates also include the remaining space in that zone.
    """
    for _ in range(300):
        if request.zone=='scattered':
            yield rng.randrange(3,61)*CELL+16,rng.randrange(4,45)*CELL+16
        elif request.zone=='near_house':
            building=buildings[index%len(buildings)]
            yield (building.x+rng.choice((-1,1))*rng.randrange(7,12)*CELL,
                   building.y+rng.randrange(1,5)*CELL)
        else:
            zx,zy=ZONE[request.zone]
            yield int((zx*scene.width+rng.randint(-8,8))*CELL),int((zy*scene.height+rng.randint(-5,5))*CELL)
    asset=assets[request.asset_id]
    width,height=scene.width*CELL,scene.height*CELL
    x0,y0=asset.anchor
    candidates=[]
    for y in range(y0,height-asset.size[1]+y0+1,CELL):
        for x in range(x0,width-asset.size[0]+x0+1,CELL):
            if request.zone=='north' and y>height*.4:continue
            if request.zone=='south' and y<height*.6:continue
            if request.zone=='west' and x>width*.4:continue
            if request.zone=='east' and x<width*.6:continue
            if request.zone=='center' and not (width*.25<=x<=width*.75 and height*.25<=y<=height*.75):continue
            if request.zone=='near_house':
                distance=min(math.hypot(max(bx-x,0,x-bx-bw),max(by-y,0,y-by-bh))
                             for bx,by,bw,bh in (visual_rect(b,assets) for b in buildings))
                if distance>8*CELL:continue
            candidates.append((x,y))
    rng.shuffle(candidates)
    if request.zone in ZONE:
        zx,zy=ZONE[request.zone]
        candidates.sort(key=lambda p:(p[0]-zx*width)**2+(p[1]-zy*height)**2)
    yield from candidates


def compile_world(spec: SceneSpec, assets: dict[str, Asset], seed=42, prompt="") -> World:
    rng = random.Random(seed)
    for b in spec.buildings:
        if b.asset_id not in assets or assets[b.asset_id].category != "building" or not assets[b.asset_id].door:
            raise ValueError(f"建筑模板不可用：{b.asset_id}")
    for p in [*spec.outdoors, *(p for b in spec.buildings for p in b.interior.furniture)]:
        if p.asset_id not in assets:
            raise ValueError(f"不存在的资源 ID：{p.asset_id}")
        if assets[p.asset_id].category not in ("prop", "nature", "furniture"):
            raise ValueError(f"不能作为物体放置：{p.asset_id}")
    terrain = [["grass"] * 64 for _ in range(48)]
    if spec.pond:
        for y in range(8, 19):
            for x in range(47, 59):
                if ((x-53)/5.7)**2+((y-13)/4.6)**2 < 1:
                    terrain[y][x] = "water"
    outdoor = Scene(id="outdoor", name=spec.title, kind="outdoor", width=64, height=48,
                    terrain=terrain, entities=[], portals=[], spawn=(32*CELL+16, 37*CELL+16))
    terrain = outdoor.terrain
    scenes = {"outdoor": outdoor}
    reserved = [(outdoor.spawn[0]-48,outdoor.spawn[1]-48,96,96)]
    buildings = []
    for index, b in enumerate(spec.buildings):
        a = assets[b.asset_id]
        zx, zy = ZONE[b.zone]
        candidate = None
        for attempt in range(200):
            x = (int(zx*64) + (rng.randint(-16,16) if attempt else 0))*CELL
            y = (int(zy*48) + (rng.randint(-9,9) if attempt else 0))*CELL
            e = Entity(id=f"building_{index}", asset_id=a.id, x=x, y=y)
            vr = visual_rect(e,assets)
            if vr[0] < 48 or vr[1] < 48 or vr[0]+vr[2] > 64*CELL-48 or vr[1]+vr[3] > 48*CELL-160:
                continue
            if any(intersects(vr, visual_rect(other,assets)) for other in buildings):
                continue
            cr = entity_rect(e,assets)
            if cr and any(intersects(cr,r) for r in solid_rects(outdoor,assets)):
                continue
            candidate = e; break
        if candidate is None:
            raise ValueError("地图无法容纳这些建筑，请减少数量或换小型建筑。")
        e = candidate
        buildings.append(e); outdoor.entities.append(e)
        dx, dy = a.door
        door_x, door_y = e.x+dx,e.y+dy
        if index == 0:
            outdoor.spawn = (door_x, door_y + 96)
            reserved[0] = (door_x-48, door_y+48, 96, 112)
        return_spawn = (door_x, door_y+56)
        reserved.append((door_x-48,door_y-8,96,112))
        # Connect entrance to the spawn with a two-cell-wide path.
        x, y = int(door_x//CELL), int(door_y//CELL)
        goal_x, goal_y = 32, 44
        points = []
        while y != goal_y:
            points.append((x,y)); y += 1 if y < goal_y else -1
        while x != goal_x:
            points.append((x,y)); x += 1 if x < goal_x else -1
        points.append((x,y))
        for px,py in points:
            for tx,ty in ((px,py),(px+1,py)):
                if 0<=tx<64 and 0<=ty<48 and terrain[ty][tx] != "water": terrain[ty][tx]="path"
        room_id=f"interior_{index}"
        room=make_room(b.interior, room_id, assets, rng)
        room.portals.append(Portal(id=f"exit_{index}",rect=(8*CELL,14*CELL,2*CELL,2*CELL),
            target_scene="outdoor",target_spawn=return_spawn,label="回到室外",facing="down"))
        outdoor.portals.append(Portal(id=f"enter_{index}",rect=(door_x-24,door_y-16,48,48),
            target_scene=room_id,target_spawn=room.spawn,label=f"进入 {b.name}",facing="up"))
        scenes[room_id]=room
    # Props cannot occupy paths, entrance reservations, or building silhouettes.
    for request in spec.outdoors:
        for n in range(request.count):
            added = False
            rejections=Counter()
            for x,y in outdoor_candidates(request,outdoor,assets,buildings,rng,n):
                entity=Entity(id=f"out_{len(outdoor.entities)}",asset_id=request.asset_id,x=x,y=y)
                vr=visual_rect(entity,assets)
                if vr[0]<0 or vr[1]<0 or vr[0]+vr[2]>64*CELL or vr[1]+vr[3]>48*CELL:
                    rejections['map_bounds']+=1;continue
                cr=entity_rect(entity,assets) or (x-12,y-12,24,24)
                padding=(cr[0]-12,cr[1]-12,cr[2]+24,cr[3]+24)
                if any(intersects(padding,r) for r in reserved):
                    rejections['entrance_reserved']+=1;continue
                if any(intersects(vr,visual_rect(b,assets)) for b in buildings):
                    rejections['building_overlap']+=1;continue
                if any(intersects(padding,r) for r in solid_rects(outdoor,assets)):
                    rejections['collision']+=1;continue
                if any(terrain[ty][tx] != "grass" for ty in range(max(0,int(padding[1]//CELL)),min(48,int((padding[1]+padding[3])//CELL)+1))
                       for tx in range(max(0,int(padding[0]//CELL)),min(64,int((padding[0]+padding[2])//CELL)+1))):
                    rejections['non_ground_tile']+=1;continue
                outdoor.entities.append(entity);added=True;break
            if not added:
                raise PlacementError(request,assets[request.asset_id],n,rejections)
    asset_revision = json.dumps({aid:a.model_dump(mode='json') for aid,a in sorted(assets.items())},sort_keys=True)
    world_id = hashlib.sha256((spec.model_dump_json()+str(seed)+COMPILER_VERSION+asset_revision).encode()).hexdigest()[:12]
    world=World(id=world_id,title=spec.title,prompt=prompt,seed=seed,scenes=scenes,assets=assets,
                plan=spec,warnings=spec.unsupported_requests)
    errors=validate_world(world)
    if errors: raise ValueError("；".join(errors))
    if spec.ground_asset_id:
        ground=assets.get(spec.ground_asset_id)
        if not ground or ground.category!="tile" or ground.size!=(32,32):
            raise ValueError("自定义地面必须为已验证的 32×32 tile")
        # Transparent authored path edges contain the original grass colors;
        # custom-ground recoloring is handled in the renderer's ground palette.
        for row in outdoor.terrain:
            for x,tile in enumerate(row):
                if tile=="grass":row[x]=spec.ground_asset_id
    return world


def make_room(spec: RoomSpec, scene_id, assets, rng) -> Scene:
    width,height=18,16
    tiles=[["floor" for _ in range(width)] for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if x in (0,width-1) or y in (0,1,height-1): tiles[y][x]="wall"
    # The bottom opening is the doorway. Outer map bounds remain solid.
    tiles[height-1][8]=tiles[height-1][9]="floor"
    room=Scene(id=scene_id,name=spec.name,kind="indoor",width=width,height=height,terrain=tiles,
               entities=[],portals=[],spawn=(9*CELL,12*CELL))
    if spec.kind == 'office':
        if 'tile.office_floor' not in assets:raise ValueError('办公室地板尚未导入，请更新素材目录。')
        for row in room.terrain:
            for x, tile in enumerate(row):
                if tile == 'floor':row[x]='tile.office_floor'
        return furnish_office(room, spec, assets)
    preferred={"furniture.bed":(3.5,6),"furniture.cabinet":(14,4),"furniture.fireplace":(9,4),
               "furniture.table":(8,9),"furniture.chair":(11,9),"furniture.plant":(3,11),"furniture.lamp":(14,11)}
    preferred_zones={'furniture.bed':'west','furniture.cabinet':'east','furniture.fireplace':'north',
                     'furniture.table':'center','furniture.chair':'east','furniture.plant':'west','furniture.lamp':'east'}
    for request in spec.furniture:
        for n in range(request.count):
            added=False
            for attempt in range(200):
                if attempt==0 and n==0 and request.asset_id in preferred and request.zone==preferred_zones[request.asset_id]:
                    x,y=preferred[request.asset_id]
                else:
                    zx,zy=ZONE.get(request.zone,(.5,.5))
                    x=max(2,min(15,int(zx*width)+rng.randint(-3,3)))+.5
                    y=max(4,min(11,int(zy*height)+rng.randint(-2,2)))
                e=Entity(id=f"{scene_id}_obj_{len(room.entities)}",asset_id=request.asset_id,x=x*CELL,y=y*CELL)
                vr=visual_rect(e,assets)
                if vr[0]<CELL or vr[1]<2*CELL or vr[0]+vr[2]>17*CELL or vr[1]+vr[3]>12*CELL: continue
                if any(intersects(vr,visual_rect(other,assets)) for other in room.entities): continue
                cr=entity_rect(e,assets)
                if cr and any(intersects(cr,r) for r in solid_rects(room,assets)): continue
                room.entities.append(e);added=True;break
            if not added: raise ValueError(f"室内放不下 {request.asset_id}，请减少家具数量。")
    return room


def furnish_office(room, spec, assets):
    # Four desk bays, separate equipment positions and a two-cell central aisle.
    desks={'office.workstation', 'office.supplies_desk'}
    requests=sorted(spec.furniture, key=lambda p:p.asset_id not in desks)
    for request in requests:
        if request.asset_id in desks:
            candidates=[(4,6),(13,6),(4,10),(13,10)]
        else:
            candidates=[(8,4),(11,4),(2,5),(16,5),(2,9),(16,9),(4,12),(13,12),(5,4),(14,4)]
        zx,zy=ZONE.get(request.zone,(.5,.5))
        candidates=sorted(candidates,key=lambda p:(p[0]-zx*room.width)**2+(p[1]-zy*room.height)**2)
        for _ in range(request.count):
            for x,y in candidates:
                e=Entity(id=f'{room.id}_obj_{len(room.entities)}',asset_id=request.asset_id,x=x*CELL,y=y*CELL)
                vr=visual_rect(e,assets)
                if vr[0]<CELL or vr[1]<2*CELL or vr[0]+vr[2]>17*CELL or vr[1]+vr[3]>12*CELL:continue
                if intersects(vr,(8*CELL,5*CELL,2*CELL,10*CELL)):continue
                if any(intersects(vr,visual_rect(other,assets)) for other in room.entities):continue
                room.entities.append(e);break
            else:raise ValueError(f'办公室放不下 {request.asset_id}，请减少家具数量。')
    return room


def save_world(world: World, root: Path) -> Path:
    """Snapshot only used images. A world continues to work after catalog updates."""
    import shutil
    folder=root/"worlds"/world.id
    image_dir=folder/"assets"
    image_dir.mkdir(parents=True,exist_ok=True)
    copy=world.model_copy(deep=True)
    used={e.asset_id for s in world.scenes.values() for e in s.entities}
    used.update(aid for aid,a in world.assets.items() if a.category in ("tile","autotile","character"))
    copy.assets={aid:copy.assets[aid] for aid in used}
    for aid,a in copy.assets.items():
        source=root/a.image
        actual=hashlib.sha256(source.read_bytes()).hexdigest()
        if a.sha256 and actual != a.sha256: raise ValueError(f"素材已变动，请重新导入：{aid}")
        target=image_dir/f"{aid}.png"
        if source.resolve()!=target.resolve(): shutil.copy2(source,target)
        a.image=str(target.relative_to(root))
    path=folder/"world.json"
    temp=folder/"world.tmp"
    temp.write_text(copy.model_dump_json(indent=2),encoding="utf-8");temp.replace(path)
    return path


def load_world(path: Path) -> World:
    return World.model_validate_json(path.read_text(encoding="utf-8"))
