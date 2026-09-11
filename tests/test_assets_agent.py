import json
from pathlib import Path

import pytest
from PIL import Image

from wonderland.agent import Generator,normalize_generated
from wonderland.catalog import Catalog,digest
from wonderland.config import Settings,load_credentials
from wonderland.models import Asset,AssetNeed,SceneSpec


def test_bare_and_dotenv_keys_are_loaded_without_execution(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    (tmp_path/'key.env').write_text('sk-example-test-only')
    assert load_credentials(tmp_path)=='sk-example-test-only'
    (tmp_path/'key.env').write_text('OPENAI_API_KEY="sk-example-other"\n')
    assert load_credentials(tmp_path)=='sk-example-other'
    assert capsys.readouterr().out==''


def test_response_schema_uses_supported_homogeneous_arrays():
    schema=SceneSpec.model_json_schema()
    assert 'prefixItems' not in json.dumps(schema)
    assert 'items' in schema['$defs']['AssetNeed']['properties']['size_cells']


def test_generated_prop_keeps_transparency_and_native_pixel_density(tmp_path):
    need=AssetNeed(key='test_lamp',description='lamp',category='prop',size_cells=[2,3],solid=True)
    im=Image.new('RGBA',(512,512));im.paste((70,110,180,255),(180,80,330,440));source=tmp_path/'input.png';im.save(source)
    output=tmp_path/'out.png';normalize_generated(source,output,need)
    image=Image.open(output)
    assert image.size==(64,96)
    assert image.getpixel((0,0))[3]==0
    for y in range(0,96,2):
        for x in range(0,64,2):assert len({image.getpixel((x+dx,y+dy)) for dx in (0,1) for dy in (0,1)})==1


def test_opaque_prop_is_rejected(tmp_path):
    im=Image.new('RGB',(128,128),'white');p=tmp_path/'opaque.png';im.save(p)
    need=AssetNeed(key='a',description='a',category='prop',size_cells=[1,1],solid=False)
    with pytest.raises(ValueError,match='透明'):normalize_generated(p,tmp_path/'out.png',need)


def test_generated_terrain_locks_opposing_edges(tmp_path):
    im=Image.new('RGB',(64,64));im.putdata([(x*4,y*4,(x+y)*2) for y in range(64) for x in range(64)])
    p=tmp_path/'in.png';im.save(p)
    need=AssetNeed(key='blue_grass',description='blue grass',category='terrain',size_cells=[1,1],solid=False)
    out=tmp_path/'out.png';normalize_generated(p,out,need);im=Image.open(out)
    assert all(im.getpixel((0,y))==im.getpixel((31,y)) for y in range(32))
    assert all(im.getpixel((x,0))==im.getpixel((x,31)) for x in range(32))


def test_generated_asset_cache_does_not_call_api(tmp_path):
    import hashlib
    from wonderland.config import STYLE
    settings=Settings(root=tmp_path)
    need=AssetNeed(key='crystal',description='crystal',category='prop',size_cells=[1,1],solid=True)
    signature=hashlib.sha256((need.model_dump_json()+STYLE+'normalize-v1'+settings.image_model).encode()).hexdigest()[:16]
    p=tmp_path/'sprite.png';Image.new('RGBA',(32,32),'blue').save(p)
    c=Catalog(tmp_path)
    a=Asset(id='generated.'+signature,name='crystal',category='prop',tags=['crystal'],source='sprite.png',image='sprite.png',size=(32,32),anchor=(16,30),sha256=digest(p))
    c.register(a)
    g=Generator(settings,progress=lambda msg:None)
    assert g.resolve_asset(need,c).id==a.id
    assert not g.job.get('calls')
    c.close()


def test_palette_preserves_tiny_colored_indicator_without_changing_pixel_density(tmp_path):
    # Many similar cabinet shades must not erase a rare green status display.
    source=tmp_path/'indicator.png'
    body=Image.new('RGB',(46,30))
    body.putdata([(50+(i*7)%100,55+(i*11)%100,70+(i*13)%100) for i in range(46*30)])
    body.putpixel((22,3),(20,250,30));body.putpixel((23,3),(20,250,30))
    im=Image.new('RGBA',(48,32));im.paste(body,(1,1));im.save(source)
    need=AssetNeed(key='checkout',description='收银台',category='furniture',size_cells=[3,2],solid=True)
    out=tmp_path/'normalized.png';normalize_generated(source,out,need)
    with Image.open(out) as result:
        assert result.size==(96,64)
        assert list(result.get_flattened_data()).count((20,250,30,255))==8
        assert result.getpixel((0,0))[3]==0
        for y in range(0,64,2):
            for x in range(0,96,2):
                assert len({result.getpixel((x+dx,y+dy)) for dx in (0,1) for dy in (0,1)})==1


def test_rejected_review_is_cached_until_pixels_change(tmp_path):
    import hashlib
    from types import SimpleNamespace
    from wonderland.agent import VisualReview
    from wonderland.config import STYLE
    settings=Settings(root=tmp_path)
    need=AssetNeed(key='counter',description='收银台',category='furniture',size_cells=[3,2],solid=True)
    signature=hashlib.sha256((need.model_dump_json()+STYLE+'normalize-v1'+settings.image_model).encode()).hexdigest()[:16]
    folder=tmp_path/'assets/generated'/signature;folder.mkdir(parents=True)
    source=Image.new('RGBA',(48,32));source.paste((50,100,160,255),(1,1,47,31))
    for i in range(2):source.save(folder/f'original_{i}.png')
    references=tmp_path/'assets/previews/catalog.png';references.parent.mkdir(parents=True)
    Image.new('RGB',(32,32),'white').save(references)
    cat=Catalog(tmp_path)
    gen=Generator(settings,progress=lambda message:None)
    gen.client=SimpleNamespace(responses=SimpleNamespace(parse=None))
    calls=[]
    def reject(kind,method,**kwargs):
        assert kind=='asset_review', 'Saved originals must not trigger another image request'
        calls.append(kind)
        return SimpleNamespace(output_parsed=VisualReview(accepted=False,issues=['主要轮廓不清'],explanation='拒绝'))
    gen.api_call=reject
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError,match='仍未通过验证'):gen.resolve_asset(need,cat)
        assert len(calls)==2  # two attempts total, not two more on every retry
        source.paste((180,40,60,255),(1,1,47,31));source.save(folder/'original_0.png')
        with pytest.raises(RuntimeError,match='仍未通过验证'):gen.resolve_asset(need,cat)
        assert len(calls)==3  # changed pixels invalidate only the changed attempt
        assert not cat.all()  # rejected candidates never become usable assets
    finally:cat.close()
