from enum import Enum

class Gnmi_Mode(Enum):
    """
    Enum to determine the operation mode of TimeMachine object and so GnmiClient object.
    """
    GET_SERIAL = 1
    GET_PARALLEL = 2
    SUBSCRIBE_ON_CHANGE = 3