import sys, os
# Add EhrAgent root so 'from tools import tabtools' works in exec() during tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
# Add ehragent dir so pipeline.py, medagent.py etc are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
