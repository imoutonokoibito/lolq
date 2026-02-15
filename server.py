from flask import Flask, jsonify, send_from_directory, request
import json, os

app = Flask(__name__, static_folder='static')
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def migrate_config(cfg):
    """Convert old champions.{role}.order format to layouts + roles format"""
    if "layouts" in cfg:
        return cfg
    layouts = {}
    roles = {}
    nid = 1
    for role, data in cfg.get("champions", {}).items():
        ids = []
        for e in data.get("order", []):
            if isinstance(e, str):
                e = {"champion": e, "spells": [], "runes": []}
            c = e.get("champion", "")
            s = e.get("spells", [])
            r = e.get("runes", [])
            found = next((lid for lid, l in layouts.items()
                          if l["champion"] == c and l["spells"] == s and l["runes"] == r), None)
            if found:
                ids.append(found)
            else:
                lid = str(nid); nid += 1
                layouts[lid] = {"champion": c, "spells": s, "runes": r}
                ids.append(lid)
        roles[role] = ids
    fb = cfg.get("fallback", {})
    new_fb = {"mode": fb.get("mode", "random_default"), "layout_id": ""}
    if fb.get("mode") == "fallback_layout" and fb.get("fallback_layout", {}).get("champion"):
        lid = str(nid); nid += 1
        layouts[lid] = {"champion": fb["fallback_layout"].get("champion", ""),
                        "spells": fb["fallback_layout"].get("spells", []),
                        "runes": fb["fallback_layout"].get("runes", [])}
        new_fb["layout_id"] = lid
    if new_fb["mode"] == "other_roles":
        new_fb["mode"] = "random_default"
    return {"bans": cfg.get("bans", []), "layouts": layouts, "roles": roles, "fallback": new_fb}

@app.route('/api/config', methods=['GET'])
def get_config():
    with open(CONFIG) as f:
        cfg = json.load(f)
    if "layouts" not in cfg:
        cfg = migrate_config(cfg)
        with open(CONFIG, 'w') as f:
            json.dump(cfg, f, indent=2)
    return jsonify(cfg)

@app.route('/api/config', methods=['POST'])
def save_config():
    with open(CONFIG, 'w') as f:
        json.dump(request.json, f, indent=2)
    return jsonify({'ok': True})

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:p>')
def static_files(p):
    return send_from_directory('static', p)

if __name__ == '__main__':
    app.run(port=5005)
