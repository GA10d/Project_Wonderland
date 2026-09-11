import json
import queue
import shutil
from types import SimpleNamespace

import pytest

from wonderland.agent import Generator
from wonderland.catalog import Catalog
from wonderland.config import ROOT, Settings
from wonderland.diagnostics import JobLock, redact
from wonderland.models import BuildingSpec, Placement, RoomSpec
from wonderland.runtime import Game
from wonderland.world import compile_world, demo_spec, validate_world, visual_rect, intersects


def office_spec():
    spec=demo_spec()
    spec.biome='urban';spec.pond=False;spec.outdoors=[]
    spec.buildings=[BuildingSpec(asset_id='house.cabin',name='办公室',zone='north',
        interior=RoomSpec(name='办公室',kind='office',furniture=[
            Placement(asset_id=aid,count=count,zone=zone) for aid,count,zone in [
                ('office.workstation',2,'west'),('office.supplies_desk',2,'east'),
                ('office.printer',1,'west'),('office.water',1,'east'),('office.whiteboard',1,'north'),
                ('office.coffee',1,'south'),('office.server',1,'north'),('office.plant',1,'south')]]))]
    return spec


@pytest.mark.parametrize('seed',[1,42,107])
def test_office_has_many_furnished_desks_clear_aisle_and_working_door(assets,seed):
    world=compile_world(office_spec(),assets,seed)
    room=world.scenes['interior_0']
    assert len(room.entities)==10
    assert not validate_world(world)
    assert room.terrain[12][9]=='tile.office_floor'
    assert all(not intersects(visual_rect(e,assets),(8*32,5*32,2*32,10*32)) for e in room.entities)
    game=Game(world,headless=True)
    for _ in range(80):game.move(0,-1,1/60)
    assert game.interact() and game.scene_id=='interior_0'
    game.release_interact()
    for _ in range(32):game.move(0,1,1/60)
    assert game.interact() and game.scene_id=='outdoor'


def test_office_assets_and_existing_generated_ground_are_visible_to_planner(assets):
    cat=Catalog()
    try:brief={a['id']:a for a in cat.brief()}
    finally:cat.close()
    assert brief['office.workstation']['category']=='furniture'
    assert brief['office.printer']['category']=='furniture'
    for a in assets.values():
        if a.category=='tile' and a.provenance.get('kind')=='openai_generated':assert a.id in brief


def test_failed_api_retry_success_and_cache_have_complete_redacted_audit(tmp_path,monkeypatch,assets):
    import wonderland.agent as agent
    for a in assets.values():
        target=tmp_path/a.image;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/a.image,target)
    cat=SimpleNamespace(all=lambda:assets,brief=lambda:[],close=lambda:None)
    monkeypatch.setattr(agent,'ensure_catalog',lambda root:cat)
    calls=[]
    class APIError(Exception):
        status_code=429;request_id='req_failure'
        body={'message':'temporary rate limit sk-test-secret'}
    def parse(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise APIError()
        return SimpleNamespace(output_parsed=office_spec(),usage=None,model='test-model',_request_id='req_success')
    monkeypatch.setattr(Settings,'client',lambda self:SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    gen=Generator(Settings(root=tmp_path),progress=lambda msg:None)
    with pytest.raises(APIError):gen.generate('office')
    failed=json.loads(gen.job_path.read_text())
    assert failed['stage']=='failed' and failed['failed_stage']=='planning'
    assert 'sk-test-secret' not in gen.job_path.read_text()
    result=gen.generate('office')
    assert result.is_file()
    completed=json.loads(gen.job_path.read_text())
    assert completed['stage']=='complete' and 'error' not in completed and 'failed_stage' not in completed
    assert gen.generate('office')==result and len(calls)==2
    lines=gen.log.path.read_text();events=[json.loads(line) for line in lines.splitlines()]
    assert 'sk-test-secret' not in lines and '[REDACTED]' in lines
    failure=next(e for e in events if e['event']=='api_failed')
    assert failure['http_status']==429 and failure['request_id']=='req_failure' and failure['stack']
    success=next(e for e in events if e['event']=='api_completed')
    assert success['model']=='test-model' and success['request_id']=='req_success'
    assert success['duration_seconds']>=0
    assert events[-1]['event']=='run_completed' and events[-1]['cached']
    assert len({e['run_id'] for e in events})==3


def test_same_job_cannot_be_run_concurrently(tmp_path):
    with JobLock(tmp_path/'job.lock'):
        with pytest.raises(RuntimeError,match='正在运行'):
            with JobLock(tmp_path/'job.lock'):pass
    with JobLock(tmp_path/'job.lock'):pass


def test_ui_marks_generation_failure_without_claiming_old_preview_is_new():
    from wonderland.studio import Studio
    studio=Studio.__new__(Studio)
    studio.generator=None;studio.messages=queue.Queue();studio.running=True;studio.error=False
    studio.selected='previous-world';studio.messages.put(('error','素材 workstation 检查失败'))
    studio.drain_messages()
    assert not studio.running and studio.error
    assert studio.status.startswith('本次生成失败，未产生新场景。')
    assert studio.selected=='previous-world'


def test_credentials_and_image_data_are_removed_from_diagnostics():
    value={'api_key':'arbitrary-secret','error':'Bearer secret-token sk-demo-secret',
           'image':'data:image/png;base64,AAABBB==','message':'OPENAI_API_KEY=secret'}
    cleaned=json.dumps(redact(value))
    assert not any(x in cleaned for x in ('arbitrary-secret','secret-token','sk-demo-secret','AAABBB','KEY=secret'))
