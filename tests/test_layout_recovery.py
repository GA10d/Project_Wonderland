import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest

from wonderland.agent import Generator
from wonderland.config import ROOT, STYLE, Settings
from wonderland.models import AssetNeed, Placement
from wonderland.world import (COMPILER_VERSION, PlacementError, compile_world, demo_spec,
                              intersects, load_world, validate_world, visual_rect)


@pytest.fixture
def snow_plan(assets):
    # The failed job placed five 4x4 peaks north of the 576x512 country house.
    # Its entire original north sampling box is covered by the house silhouette.
    need=AssetNeed(key='snowy_peak_scenery',description='积雪山峰',category='prop',size_cells=[4,4],solid=True)
    signature=hashlib.sha256((need.model_dump_json()+STYLE+'normalize-v1'+Settings().image_model).encode()).hexdigest()[:16]
    peak=assets['prop.rock'].model_copy(update=dict(id='generated.'+signature,name='积雪山峰',
        size=(128,128),anchor=(64,124),collision=(-32,-16,64,16)))
    available={**assets,peak.id:peak}
    spec=demo_spec();spec.pond=False
    spec.outdoors=[Placement(asset_id=peak.id,count=5,zone='north'),
                   Placement(asset_id='tree.pine',count=5,zone='west'),
                   Placement(asset_id='tree.pine',count=5,zone='east')]
    return spec,available,need,peak


@pytest.mark.parametrize('seed',[42,43,44])
def test_large_house_does_not_exhaust_north_region(snow_plan,seed):
    spec,assets,_,peak=snow_plan
    world=compile_world(spec,assets,seed)
    outdoor=world.scenes['outdoor'];house=outdoor.entities[0]
    peaks=[e for e in outdoor.entities if e.asset_id==peak.id]
    assert len(peaks)==5
    assert len(outdoor.entities)==16  # house + all peaks + ten trees
    assert all(e.y<outdoor.height*32*.4 for e in peaks)
    assert all(not intersects(visual_rect(e,assets),visual_rect(house,assets)) for e in peaks)
    assert not validate_world(world)


def test_impossible_placement_keeps_failure_counts_and_reason(snow_plan):
    spec,assets,_,peak=snow_plan
    assets[peak.id]=peak.model_copy(update=dict(size=(2048,1536),anchor=(1024,1532)))
    with pytest.raises(PlacementError) as failure:compile_world(spec,assets,42)
    details=failure.value.layout_details
    assert details['asset_id']==peak.id
    assert details['zone']=='north' and details['placed']==0 and details['requested']==5
    assert details['rejections']['map_bounds']>0


def test_retry_saved_layout_failure_reuses_plan_and_assets_without_api(snow_plan,tmp_path,monkeypatch):
    import wonderland.agent as agent
    spec,assets,need,peak=snow_plan
    for a in assets.values():
        target=tmp_path/a.image;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/a.image,target)
    spec.outdoors[0].asset_id='generated.'+need.key;spec.missing_assets=[need]
    job_id='0123456789abcdef'
    path=tmp_path/'data/jobs'/f'{job_id}.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(prompt='雪山大木屋',seed=42,stage='failed',failed_stage='compiling',
                                   error='旧布局失败',compiler_version='0.1.2',plan=spec.model_dump(mode='json'),calls=[])))
    cat=SimpleNamespace(all=lambda:assets,brief=lambda:[],close=lambda:None)
    monkeypatch.setattr(agent,'ensure_catalog',lambda root:cat)
    monkeypatch.setattr(Settings,'client',lambda self:object())
    gen=Generator(Settings(root=tmp_path),progress=lambda msg:None)
    monkeypatch.setattr(gen,'api_call',lambda *args,**kwargs:pytest.fail('Retry must not call the API'))
    world_path=gen.resume(job_id)
    world=load_world(world_path)
    assert sum(e.asset_id==peak.id for e in world.scenes['outdoor'].entities)==5
    job=json.loads(path.read_text())
    assert job['stage']=='complete' and 'error' not in job and 'failed_stage' not in job
    assert job['compiler_version']==COMPILER_VERSION and job['calls']==[]
    events=[json.loads(row) for row in gen.log.path.read_text().splitlines()]
    assert events[0]['previous_error']=='旧布局失败'
    assert any(e['event']=='asset_reused' for e in events)
    assert events[-1]['event']=='run_completed'
