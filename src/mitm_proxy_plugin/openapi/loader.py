import json
import yaml

def load_spec(path: str) -> dict:
    with open(path, 'r') as f:
        if path.endswith(('.yaml', '.yml')):
            return yaml.safe_load(f)
        return json.load(f)