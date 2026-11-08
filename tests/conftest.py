import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("RARITAN_HOST", "pdu-test.local")
os.environ.setdefault("RARITAN_USER", "tester")
os.environ.setdefault("RARITAN_PASS", "secret")
