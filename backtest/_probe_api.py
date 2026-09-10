import inspect, sys
sys.path.insert(0, r"D:\projects\trading\4H-1H-Trading-Algo")
from backtest import experiments
print("type:", type(experiments))
print("dir:", [x for x in dir(experiments) if not x.startswith('__')])
src = inspect.getsource(experiments)
print(src[:3000])
