import argparse
from jetson_browser.services import start_model, stop, wait_model

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['start', 'stop'])
parser.add_argument('model', choices=['laya', 'qwen', 'all'])
parser.add_argument('--mtp', choices=['on', 'off'])
args = parser.parse_args()
for model in (['laya', 'qwen'] if args.model == 'all' else [args.model]):
    if args.action == 'stop':
        stop(model)
    else:
        start_model(model, mtp=None if not args.mtp else args.mtp == 'on')
        wait_model(model)
        print(model + ' ready on Jetson', flush=True)
