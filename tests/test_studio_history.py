import queue
from types import SimpleNamespace

from wonderland.diagnostics import EventLog
from wonderland.studio import Studio
from wonderland.world import compile_world, demo_spec


def test_running_studio_discovers_world_saved_by_another_process(tmp_path,assets):
    world=compile_world(demo_spec(),assets)
    old=tmp_path/'worlds/old/world.json';old.parent.mkdir(parents=True)
    old.write_text(world.model_dump_json())
    studio=Studio.__new__(Studio)
    studio.root=tmp_path;studio.ui_log=EventLog(tmp_path,'studio')
    studio.history_signature=None;studio.history=[];studio.last_history_check=0.;studio.library_notice=''
    studio.selected=old;studio.prompt='An unfinished draft'
    studio.refresh_history()
    # A second process writes a completed world after this window has loaded its list.
    new=tmp_path/'worlds/new/world.json';new.parent.mkdir(parents=True)
    world.id='new';world.title='熔岩魔王官邸';new.write_text(world.model_dump_json())
    studio.poll_history()
    assert studio.history[0]==('熔岩魔王官邸',new)
    assert '熔岩魔王官邸' in studio.library_notice
    assert studio.selected==old and studio.prompt=='An unfinished draft'
    assert not studio.refresh_history(force=False)


def test_old_generator_does_not_override_selected_world_log():
    studio=Studio.__new__(Studio)
    studio.running=False;studio.generator=SimpleNamespace(job_path='old-office.json')
    studio.job_path='selected-volcano.json';studio.messages=queue.Queue()
    studio.drain_messages()
    assert studio.job_path=='selected-volcano.json'
