"""Recreate synthetic public/control fixtures only on the marked disposable local cluster."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rudo.synthetic import bootstrap
if __name__=='__main__':
    bootstrap()
    print('Synthetic observer fixture ready on the marked loopback database. No remote access used.')
