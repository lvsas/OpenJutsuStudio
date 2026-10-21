#!/usr/bin/env python3
"""No-GPU live SDK audit; uploads require explicit --upload-existing opt-in.

Run with the repository venv. Only already-validated take.* files may be
uploaded, under a fresh input/opengenjutsu-sdk-spike/<uuid>/ namespace.
Never submits a workflow, reconstructs output asset IDs, or installs nodes.
The owned scratch proxy is stopped even when a probe fails.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import resource
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlsplit
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from comfy_sdk import Comfy
from comfy_low import ComfyLow
from h3_artifact_transport import download_h3_artifacts
from timeline_artifacts import validate_h3_artifact_set

SUFFIXES = {'video': '.mp4', 'mctx': '.mctx.safetensors',
            'conditioning': '.cond.safetensors'}
MAX_JSON = 16 * 1024 * 1024


def get_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(MAX_JSON + 1)
        if len(data) > MAX_JSON:
            raise ValueError('Audit JSON response exceeded 16 MiB bound')
        return json.loads(data)


def digest_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
            size += len(block)
    return {'sha256': digest.hexdigest(), 'size_bytes': size}


def rss_kib(pid):
    # Only the process started by this script is inspected.
    text = Path(f'/proc/{pid}/status').read_text()
    return {line.split(':')[0]: int(line.split()[1])
            for line in text.splitlines() if line.startswith(('VmRSS:', 'VmHWM:'))}


def run(args):
    source = args.source.resolve(strict=True)
    scratch = args.scratch.resolve(strict=True)
    paths = {role: source / ('take' + suffix) for role, suffix in SUFFIXES.items()}
    manifest = validate_h3_artifact_set(**paths, root=source).to_manifest()
    run_dir = scratch / ('h3-sdk-roundtrip-' + uuid.uuid4().hex)
    run_dir.mkdir(mode=0o700)
    report = {'started_at': datetime.now(timezone.utc).isoformat(),
              'source_manifest': manifest, 'source_root': str(source),
              'versions': {p: importlib.metadata.version(p)
                           for p in ('comfy-sdk', 'comfy-api-proxy')},
              'run_dir': str(run_dir), 'gpu_jobs_submitted': 0,
              'upload_opt_in': args.upload_existing}
    evidence = run_dir / 'evidence.json'

    def save():
        evidence.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    command = [str(Path(sys.executable).parent / 'comfy-api-proxy'), 'run',
               '--host', '127.0.0.1', '--port', str(port), '--comfyui', args.upstream,
               '--state-dir', str(run_dir / 'proxy-state'), '--max-upload-mb', '100']
    report['proxy_command'] = command
    env = os.environ.copy()
    env['TMPDIR'] = str(run_dir)
    env.pop('COMFY_API_KEY', None)
    env.pop('COMFY_BASE_URL', None)
    done = threading.Event()
    memory = {'max_sampled_rss_kib': 0}
    save()
    with (run_dir / 'proxy.log').open('wb') as log:
        proxy = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=env)
        try:
            for _ in range(100):
                if proxy.poll() is not None:
                    raise RuntimeError('Owned scratch proxy exited during startup; see proxy.log')
                try:
                    health = get_json(base + '/api/v2/health')
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Owned scratch proxy did not become healthy')
            report['health'] = health
            if args.upstream not in json.dumps(health):
                raise RuntimeError('Proxy health did not identify the requested upstream')
            report['proxy_memory_before'] = rss_kib(proxy.pid)

            def monitor():
                while not done.wait(.01):
                    try:
                        value = rss_kib(proxy.pid)
                        memory['max_sampled_rss_kib'] = max(memory['max_sampled_rss_kib'],
                                                           value.get('VmRSS', 0))
                        memory['max_hwm_kib'] = max(memory.get('max_hwm_kib', 0),
                                                  value.get('VmHWM', 0))
                    except OSError:
                        return

            sampler = threading.Thread(target=monitor, daemon=True)
            sampler.start()
            os.environ['COMFY_BASE_URL'] = base
            # Explicitly prevent inheriting a production credential for this unauthenticated proxy.
            os.environ.pop('COMFY_API_KEY', None)
            with Comfy() as client, ComfyLow(base, timeout=180) as low:
                history = get_json(args.upstream + '/history?max_items=100')
                h3_history, videos = [], []
                for job_id, entry in history.items():
                    graph = entry.get('prompt', [None, None, {}])[2]
                    savers = {key: node['class_type'] for key, node in graph.items()
                              if isinstance(node, dict) and 'Save' in node.get('class_type', '')
                              and 'MCtx' in node.get('class_type', '')}
                    if savers:
                        sdk_job = client.jobs.get(job_id)
                        h3_history.append({'job_id': job_id, 'savers': savers,
                                           'status': entry.get('status', {}).get('status_str'),
                                           'output_nodes': list(entry.get('outputs', {})),
                                           'sdk_status': sdk_job.status,
                                           'sdk_outputs': [{'id': item.id, 'name': item.name,
                                                            'node_id': item.node_id}
                                                           for item in sdk_job.outputs]})
                    for node_id, output in entry.get('outputs', {}).items():
                        for items in output.values():
                            if isinstance(items, list):
                                for descriptor in items:
                                    if isinstance(descriptor, dict) and str(descriptor.get('filename', '')).endswith('.mp4'):
                                        videos.append((job_id, node_id, descriptor['filename']))
                report['history_audit'] = {'count': len(history), 'requested_max_items': 100,
                                            'h3_savers': h3_history,
                                            'published_mp4_count': len(videos)}
                report['node_contracts'] = {}
                for name in ('H3SaveVideoWithMCtx', 'H3TrimAndSaveVideoWithMCtx',
                             'H3SaveMCtxForVideo', 'H3LoadVideoWithMCtx'):
                    schema = get_json(args.upstream + '/object_info/' + name)[name]
                    record = {key: schema.get(key) for key in ('output', 'output_name', 'description', 'python_module')}
                    if name == 'H3LoadVideoWithMCtx':
                        record['clip_tooltip'] = schema['input']['required']['clip'][1]['tooltip']
                    report['node_contracts'][name] = record
                save()
                if videos:
                    # This filename was actually published; it is NOT the source family's MP4.
                    job_id, node_id, filename = videos[0]
                    job = client.jobs.get(job_id)
                    outputs = job.get_outputs(node_id)
                    selected = [output for output in outputs if output.name == filename]
                    if len(selected) != 1:
                        raise RuntimeError('Published SDK output selection was ambiguous')
                    output = selected[0]
                    dest = run_dir / 'existing-sdk-output.mp4'
                    output.to_file(dest)
                    report['sdk_existing_mp4'] = {'job_id': job.id, 'node_id': node_id,
                                                  'output_id': output.id, 'name': output.name,
                                                  **digest_file(dest)}
                    try:
                        download_h3_artifacts(job, node_id, run_dir / 'not-a-family')
                    except ValueError as exc:
                        report['incomplete_family_guard'] = str(exc)
                    else:
                        raise RuntimeError('Unexpected family: inspect before making a claim')
                    if (run_dir / 'not-a-family').exists():
                        raise RuntimeError('Incomplete family was exposed')
                save()
                if args.upload_existing:
                    namespace = 'input/opengenjutsu-sdk-spike/' + uuid.uuid4().hex
                    report['upload_namespace'] = namespace
                    report['uploads'] = {}
                    readback = run_dir / 'readback'
                    readback.mkdir()
                    for role, path in paths.items():
                        # Public official low-level SDK, not a private transport patch.
                        # from_file drops directories; from_stream buffers everything.
                        with path.open('rb') as stream:
                            asset = low.post_assets(stream,
                                'video/mp4' if role == 'video' else 'application/octet-stream',
                                namespace + '/' + path.name, file_size=path.stat().st_size,
                                tags=['opengenjutsu-sdk-spike'], idempotency_key=str(uuid.uuid4()))
                        handle = client.assets.get(asset.id)
                        if handle.file_path != namespace + '/' + path.name:
                            raise RuntimeError('Upload lost its requested namespace/association')
                        target = readback / path.name
                        with low.get_asset_content(handle.id) as response, target.open('xb') as sink:
                            count = 0
                            for block in response.iter_bytes(65536):
                                count += len(block)
                                if count > manifest['assets'][role]['size_bytes']:
                                    raise RuntimeError('Asset readback exceeded source size')
                                sink.write(block)
                        actual = digest_file(target)
                        expected = manifest['assets'][role]
                        if any(actual[k] != expected[k] for k in actual):
                            raise RuntimeError('SDK asset readback differs from the source')
                        report['uploads'][role] = {'asset_id': handle.id,
                                                   'file_path': handle.file_path,
                                                   'hash': handle.hash, 'created_new': asset.created_new,
                                                   'reference': handle.as_reference(), **actual}
                        save()
                    report['readback_manifest'] = validate_h3_artifact_set(
                        **{role: readback / path.name for role, path in paths.items()}, root=readback,
                        expected_sha256={role: data['sha256'] for role, data in manifest['assets'].items()}
                    ).to_manifest()
                    video = report['uploads']['video']
                    requested = namespace + '-dedup/take.mp4'
                    duplicate = low.asset_from_hash(video['hash'], file_path=requested,
                                                     tags=['opengenjutsu-sdk-spike'])
                    observed = client.assets.get(duplicate.id)
                    report['dedup_probe'] = {'requested_file_path': requested,
                                              'returned_file_path': observed.file_path,
                                              'same_id': duplicate.id == video['asset_id'],
                                              'asset_id': duplicate.id,
                                              'created_new': duplicate.created_new}
                    # The probe only READS the owned proxy's asset table, never job/secret data.
                    databases = list((run_dir / 'proxy-state').glob('*.sqlite*'))
                    database = next(path for path in databases if path.suffix in ('.sqlite', '.sqlite3'))
                    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
                        rows = connection.execute('SELECT id, file_path, comfy_ref FROM assets').fetchall()
                    report['actual_upstream_refs'] = [{'id': row[0], 'file_path': row[1],
                                                       'comfy_ref': json.loads(row[2]) if row[2] else None}
                                                      for row in rows if row[0] in {
                                                          value['asset_id'] for value in report['uploads'].values()}]
                    report['loader_consumption'] = 'UNVERIFIED: stock H3 loader is output-relative; uploads are input-relative. No graph submitted.'
                    save()
            report['client_maxrss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            report['proxy_memory_after'] = rss_kib(proxy.pid)
        except Exception as exc:
            report['error'] = {'class': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            done.set()
            if 'sampler' in locals():
                sampler.join(timeout=2)
            proxy.terminate()
            try:
                proxy.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proxy.kill()
                proxy.wait(timeout=5)
            report['proxy_memory_sampled'] = memory
            report['owned_proxy_exit_code'] = proxy.returncode
            report['finished_at'] = datetime.now(timezone.utc).isoformat()
            save()
            print(evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--upstream', required=True,
                        help='Explicit ComfyUI HTTP(S) endpoint; no machine-specific default')
    parser.add_argument('--upload-existing', action='store_true')
    args = parser.parse_args()
    parsed = urlsplit(args.upstream)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error('upstream must be an HTTP(S) URL without credentials/query/fragment')
    run(args)


if __name__ == '__main__':
    main()
