"""Explicit connection diagnostic. Never upload an asset or submit a workflow."""
import shutil
import time
from urllib.error import HTTPError
from compute_settings import target_mode
import readiness


def _graphs(target=None):
    from graphs import build_frame_edit, build_ripple
    from h3_graphs import build_h3_recast, H3Models
    from model_catalog import effective_bindings
    models = effective_bindings(dict(target.model_bindings) if target is not None else {})
    ltx = {f'edit_{key}':node for key,node in build_frame_edit('check.png','Connection diagnostic', model_files=models).items()}
    ltx.update({f'video_{key}':node for key,node in build_ripple('check.mp4','check.png', model_files=models).items()})
    h3 = build_h3_recast('check.mp4','check.png','Connection diagnostic',source_frames=5, models=H3Models.configured(models))
    return {'ltx':ltx,'h3':h3}


def _model_inventory(info):
    from comfy_schema import loader_choices
    from model_catalog import roles, validate_bindings
    result = {'status': 'verified', 'choices': {}}
    for role in roles():
        choices = [] if role['class_type'] not in info else loader_choices(info, role['class_type'], role['input'])
        if choices is None:
            result['status'] = 'unknown'
            continue
        accepted = []
        for name in choices:
            try:
                validate_bindings({role['key']: name})
            except ValueError:
                continue
            accepted.append(name)
        result['choices'][role['key']] = accepted
    return result


def diagnose_target(target):
    token = readiness._READ_DEADLINE.set(time.monotonic()+20)
    try:
        return _diagnose_target(target)
    finally:
        readiness._READ_DEADLINE.reset(token)


def _diagnose_target(target):
    mode = target_mode(target.base_url)
    result = {'connected':False,'ready':False,'mode':mode,'issues':[], 'warnings':[], 'engines':{}, 'model_inventory':{'status':'unknown', 'choices':{}}}
    graphs = _graphs(target)
    for name in graphs:
        result['engines'][name] = {'status':'unreachable','missing_nodes':[], 'missing_models':[],
                                  'issues':[], 'warnings':[]}
    if mode in {'comfy-cloud','comfy-api-deployment'} and not target.api_key:
        result['issues'].append('Add an API key for this Comfy target. Nothing was submitted.')
        return result
    try:
        if mode == 'comfy-cloud':
            info = readiness._object_info(target.base_url+'/api/object_info', {'X-API-Key':target.api_key})
        else:
            # Unlike Cloud, self-hosted and deployment v2 surfaces expose listing.
            # This protected read verifies the actual credential, not public health.
            readiness._probe_v2_jobs(target.base_url, target.api_key)
            info = None
            if mode == 'self-hosted':
                union = {f'{name}_{key}':node for name,graph in graphs.items() for key,node in graph.items()}
                info = readiness._target_object_info(union, target=target)
        result['connected'] = True
        if info is not None:
            result['model_inventory'] = _model_inventory(info)
        tools = [tool for tool in ('ffmpeg','ffprobe') if not shutil.which(tool)]
        if tools:
            result['issues'].append('Install local media tools: '+', '.join(tools))
        for name,graph in graphs.items():
            engine = result['engines'][name]
            if info is None:
                engine['status'] = 'unknown'
                engine['warnings'].append('API v2 connection verified; node/model inventory is not exposed by this target contract. No render was submitted.')
            else:
                try:
                    nodes, models = readiness._inventory(info, graph)
                except ValueError:
                    engine['status'] = 'unknown'
                    engine['warnings'].append('A loader inventory could not be interpreted. Check compatible filenames manually; dependencies remain unverified.')
                    continue
                engine.update(status='missing' if nodes or models or tools else 'ready',
                              missing_nodes=nodes, missing_models=models)
                if nodes or models:
                    engine['issues'].append('Install the listed dependencies on the selected ComfyUI target.')
        result['ready'] = not result['issues'] and all(e['status']=='ready' for e in result['engines'].values())
        if info is None:
            result['warnings'].append('Connected does not mean dependency-verified. Native state operations retain their stricter capability gates.')
    except HTTPError as exc:
        result['issues'].append('Authentication failed. Check the target API key.' if exc.code in {401,403}
                                else 'Cannot verify this API v2 endpoint. A raw ComfyUI URL needs the official API proxy.')
    except Exception:
        result['issues'].append('Cannot verify this API v2 target. Check its URL, authentication and availability; nothing was submitted.')
    return result
