from typing import List, Dict, Any, Optional

import pydantic


class BaseModel(pydantic.BaseModel):
    class Config:
        extra = "forbid"


#  class CheckList(BaseModel):
#  __root__: Dict[str, Check]
#  #  args: Dict[str, Dict[str, Any]] = {}

#  #  @property
#  #  def type(self) -> self:

#  def __iter__(self):
#  return iter(self.__root__)

#  def __getitem__(self, item):
#  return self.__root__[item]


class Config(BaseModel):
    checks: Dict[str, Dict[str, Optional[Dict[str, Any]]]]

    @classmethod
    def default(cls):
        return cls(
            checks={
                "*": {
                    "Chi2Test": {"threshold": 0.01},
                    "KolmogorovTest": {"threshold": 0.68},
                    "RatioCheck": {"threshold": 3},
                    "ResidualCheck": {"threshold": 1},
                    "IntegralCheck": {"threshold": 3},
                }
            }
        )
