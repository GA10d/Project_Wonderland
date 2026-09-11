from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetNeed(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,48}$")
    description: str = Field(max_length=1000)
    category: Literal["prop", "furniture", "terrain", "building"]
    size_cells: list[int] = Field(min_length=2, max_length=2)
    solid: bool


class Placement(StrictModel):
    asset_id: str
    count: int = Field(ge=1, le=30)
    zone: Literal["north", "south", "east", "west", "center", "scattered", "near_house"]


class RoomSpec(StrictModel):
    name: str
    kind: Literal['home', 'office'] = 'home'
    furniture: list[Placement] = Field(max_length=20)


class BuildingSpec(StrictModel):
    asset_id: str
    name: str
    zone: Literal["north", "south", "east", "west", "center"]
    interior: RoomSpec


class SceneSpec(StrictModel):
    title: str = Field(max_length=60)
    summary: str = Field(max_length=500)
    biome: Literal["meadow", "forest", "farm", "urban"]
    ground_asset_id: str | None = None
    pond: bool
    buildings: list[BuildingSpec] = Field(min_length=1, max_length=3)
    outdoors: list[Placement] = Field(max_length=16)
    missing_assets: list[AssetNeed] = Field(max_length=6)
    unsupported_requests: list[str]


class Asset(StrictModel):
    id: str
    name: str
    category: str
    tags: list[str]
    source: str
    image: str
    size: tuple[int, int]
    anchor: tuple[int, int]
    collision: tuple[int, int, int, int] | None = None
    footprint: tuple[int, int] = (1, 1)
    door: tuple[int, int] | None = None
    style: str = "limezu-modern-16"
    state: str = "validated"
    sha256: str = ""
    provenance: dict = Field(default_factory=dict)


class Entity(StrictModel):
    id: str
    asset_id: str
    x: float
    y: float


class Portal(StrictModel):
    id: str
    rect: tuple[float, float, float, float]
    target_scene: str
    target_spawn: tuple[float, float]
    label: str
    facing: Literal["up", "down", "left", "right"]


class Scene(StrictModel):
    id: str
    name: str
    kind: Literal["outdoor", "indoor"]
    width: int
    height: int
    terrain: list[list[str]]
    entities: list[Entity]
    portals: list[Portal]
    spawn: tuple[float, float]


class World(StrictModel):
    schema_version: int = 1
    id: str
    title: str
    prompt: str
    seed: int
    scenes: dict[str, Scene]
    assets: dict[str, Asset]
    plan: SceneSpec
    player_scene: str = "outdoor"
    warnings: list[str] = Field(default_factory=list)
