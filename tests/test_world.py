import json
import pytest

from wonderland.config import ROOT
from wonderland.models import BuildingSpec,Placement,RoomSpec
from wonderland.runtime import Game
from wonderland.world import (compile_world,demo_spec,validate_world,can_stand,
                              save_world,load_world,entity_rect)


@pytest.mark.parametrize('seed',[1,42,73,800])
def test_world_is_traversable_and_has_real_paths(assets,seed):
    world=compile_world(demo_spec(),assets,seed)
    assert not validate_world(world)
    outside=world.scenes['outdoor']
    assert sum(t=='path' for row in outside.terrain for t in row)>25
    assert len(outside.portals)==1
    assert len(world.scenes['interior_0'].entities)==7
    for scene in world.scenes.values():
        for entity in scene.entities:
            r=entity_rect(entity,assets)
            if r:assert not can_stand(scene,assets,r[0]+r[2]/2,r[1]+r[3]/2)


def test_movement_reaches_door_and_roundtrip_uses_correct_target(assets):
    world=compile_world(demo_spec(),assets,42)
    game=Game(world,headless=True)
    assert game.active_portal() is None
    for _ in range(80):game.move(0,-1,1/60)
    assert game.active_portal() is not None
    entrance=game.active_portal()
    assert game.interact()
    assert game.scene_id==entrance.target_scene
    assert (game.x,game.y)==entrance.target_spawn
    assert not game.interact()  # held E never bounces between scenes
    game.release_interact()
    assert game.active_portal() is None
    for _ in range(32):game.move(0,1,1/60)
    assert game.active_portal() is not None
    exit_portal=game.active_portal()
    assert game.interact()
    assert game.scene_id=='outdoor'
    assert (game.x,game.y)==exit_portal.target_spawn
    assert game.active_portal() is None


def test_large_delta_cannot_tunnel_through_wall(assets):
    world=compile_world(demo_spec(),assets)
    game=Game(world,headless=True);game.set_scene('interior_0',(64,320))
    for _ in range(30):game.move(-1,0,3)
    assert game.x>=32+9
    assert can_stand(game.scene,assets,game.x,game.y)


@pytest.mark.parametrize('legacy',[False,True])
def test_exit_still_works_after_walking_all_the_way_into_doorway(assets,legacy):
    world=compile_world(demo_spec(),assets)
    if legacy:
        world.scenes['interior_0'].portals[0].rect=(256,448,64,24)
    game=Game(world,headless=True);game.set_scene('interior_0')
    for _ in range(120):game.move(0,1,1/60)
    assert game.y>480  # beyond the old 24px trigger, inside the visible doorway
    assert game.active_portal() is not None
    assert game.interact()
    assert game.scene_id=='outdoor'


def test_multiple_buildings_have_distinct_interiors(assets):
    spec=demo_spec()
    spec.buildings=[BuildingSpec(asset_id='house.cabin',name=f'房屋{i}',zone=zone,
                       interior=RoomSpec(name=f'室内{i}',furniture=[])) for i,zone in enumerate(['west','east','north'])]
    world=compile_world(spec,assets,88)
    assert len(world.scenes)==4
    assert len({p.target_scene for p in world.scenes['outdoor'].portals})==3
    assert not validate_world(world)


def test_unknown_asset_is_rejected_not_silently_replaced(assets):
    spec=demo_spec();spec.outdoors.append(Placement(asset_id='invented.asset',count=1,zone='center'))
    with pytest.raises(ValueError,match='不存在的资源'):compile_world(spec,assets)


def test_determinism_and_snapshot_independence(assets,tmp_path):
    import shutil
    world=compile_world(demo_spec(),assets,900)
    assert world.model_dump()==compile_world(demo_spec(),assets,900).model_dump()
    # Save relative source paths into an isolated fake project, then delete its catalog artwork.
    for a in assets.values():
        target=tmp_path/a.image;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/a.image,target)
    path=save_world(world,tmp_path)
    shutil.rmtree(tmp_path/'assets')
    restored=load_world(path)
    assert all((tmp_path/a.image).is_file() for a in restored.assets.values())
    game=Game(restored,root=tmp_path,headless=True);game.draw()


def test_terrain_hole_is_not_filled_as_center(assets):
    from wonderland.models import Scene
    from wonderland.world import tile_mask
    scene=Scene(id='x',name='x',kind='outdoor',width=3,height=3,
                terrain=[['grass','path','path'],['path','path','path'],['path','path','path']],entities=[],portals=[],spawn=(48,48))
    mask=tile_mask(scene,1,1)
    assert mask==127
    assert f'auto.path.{mask}' in assets
    assert 'auto.path.0' in assets
