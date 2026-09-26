from .web import attach
__all__=['attach']

# BEGIN M8839_TAIL_FRESHNESS_R1
from .freshness_r1 import install_view_wrappers as _install_m8839_tail_r1
_install_m8839_tail_r1()
# END M8839_TAIL_FRESHNESS_R1
