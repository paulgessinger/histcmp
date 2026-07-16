from enum import Enum
from typing import List, Dict, Any, Optional

import pydantic


class BaseModel(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")


class Renderer3D(str, Enum):
    scatter = "scatter"
    voxel = "voxel"


class ComparisonMetric(str, Enum):
    ratio = "ratio"
    residual = "residual"
    pull = "pull"
    asymmetry = "asymmetry"


#  class CheckList(BaseModel):
#  __root__: Dict[str, Check]
#  #  args: Dict[str, Dict[str, Any]] = {}

#  #  @property
#  #  def type(self) -> self:

#  def __iter__(self):
#  return iter(self.__root__)

#  def __getitem__(self, item):
#  return self.__root__[item]


class PlotConfig(BaseModel):
    # store plain strings (use_enum_values) so the values can be formatted
    # into e.g. file suffixes directly; validate_assignment keeps CLI
    # overrides going through the same conversion
    model_config = pydantic.ConfigDict(
        extra="forbid",
        use_enum_values=True,
        validate_assignment=True,
        validate_default=True,
    )

    renderer_3d: Renderer3D = Renderer3D.voxel
    # comparison panel metric
    comparison: ComparisonMetric = ComparisonMetric.ratio
    # comparison metric for 2D/3D histograms only; set to null to fall back
    # to `comparison`
    comparison_2d3d: Optional[ComparisonMetric] = ComparisonMetric.pull

    @property
    def effective_comparison_2d3d(self) -> str:
        return self.comparison_2d3d or self.comparison


class Config(BaseModel):
    checks: Dict[str, Dict[str, Optional[Dict[str, Any]]]]
    plots: PlotConfig = PlotConfig()
