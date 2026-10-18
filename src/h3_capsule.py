"""Path-free H3 provenance; replay verifies frozen recipe and local input bytes."""
import copy
import hashlib
from pathlib import Path
from h3_recipe import ENGINE, digest_json, validate_recipe


def contained(path, media_dir):
    root = Path(media_dir).resolve()
    candidate = Path(path)
    candidate = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not candidate.is_relative_to(root) or candidate == root or not candidate.is_file():
        raise ValueError('H3 asset is missing or outside the media directory')
    return candidate


def digest_file(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def _asset(path, media_dir):
    resolved = contained(path, media_dir)
    return {'sha256': digest_file(resolved), 'size_bytes': resolved.stat().st_size}


def frozen_references(job):
    """References recorded on a job, newest key first with the historical key as fallback."""
    recorded = job.meta.get('h3_references')
    if recorded:
        return list(recorded)
    single = job.meta.get('h3_reference')
    return [single] if single else []


def capsule_references(capsule):
    """References recorded in a capsule, newest shape first with the historical one after."""
    assets = capsule.get('assets') or {}
    recorded = assets.get('references')
    if recorded:
        return list(recorded)
    single = assets.get('reference')
    return [single] if single else []


def freeze_capsule(job, recipe, source, references, result, media_dir):
    recipe = validate_recipe(recipe)
    references = list(references)
    if len(references) != recipe['reference_count']:
        raise ValueError('H3 capsule reference count does not match the frozen recipe')
    assets = {'source': _asset(source, media_dir), 'result': _asset(result, media_dir),
              'references': [_asset(path, media_dir) for path in references]}
    capsule = {
        'format': 'opengenjutsu-h3-capsule', 'schema_version': 1,
        'job_id': job.id, 'parent_job_id': job.meta.get('parent_job_id'),
        'engine': ENGINE, 'recipe': recipe, 'recipe_sha256': digest_json(recipe),
        'shot_boundaries': copy.deepcopy(recipe['shot_plan']),
        'assets': assets, 'replay': {
            'contract': 'Verified local inputs and frozen recipe; pixel-identical output is not guaranteed.',
            'model_weights_hashed': False,
        },
    }
    capsule['capsule_id'] = 'sha256:' + digest_json(capsule)
    job.meta['h3_recipe'] = copy.deepcopy(recipe)
    job.meta['h3_capsule'] = capsule
    return copy.deepcopy(capsule)


def get_capsule(job):
    """Return the frozen provenance record exactly as it was stored.

    A capsule is a historical document, not a submission: it is deliberately not
    re-validated against the current prompt policy. Doing so would make every take
    produced under an earlier policy unreadable. Policy validity is enforced when
    a take is submitted and when it is replayed.
    """
    if job.engine != ENGINE or job.status != 'done' or not job.result:
        raise ValueError('A completed H3 result is required')
    capsule = copy.deepcopy(job.meta.get('h3_capsule'))
    if not isinstance(capsule, dict):
        raise ValueError('No frozen H3 capsule exists')
    identifier = capsule.pop('capsule_id', None)
    if identifier != 'sha256:' + digest_json(capsule):
        raise ValueError('The frozen H3 capsule changed')
    capsule['capsule_id'] = identifier
    if capsule.get('engine') != ENGINE or capsule.get('job_id') != job.id:
        raise ValueError('H3 capsule identity mismatch')
    recipe = capsule.get('recipe')
    if not isinstance(recipe, dict) or capsule.get('recipe_sha256') != digest_json(recipe):
        raise ValueError('The frozen H3 recipe changed')
    return capsule


def replay_inputs(job, media_dir):
    capsule = get_capsule(job)
    try:
        recipe = validate_recipe(capsule['recipe'])
    except ValueError as exc:
        raise ValueError('This take was frozen with an earlier H3 prompt policy. Start a new take from the source instead of replaying it.') from exc
    source = contained(job.video, media_dir)
    references = [contained(path, media_dir) for path in frozen_references(job)]
    expected_references = capsule_references(capsule)
    if len(references) != len(expected_references):
        raise ValueError('A local H3 input changed after the capsule was frozen')
    for path, expected in [(source, capsule['assets'].get('source')), *zip(references, expected_references)]:
        if not expected or expected['sha256'] != digest_file(path) \
                or expected['size_bytes'] != path.stat().st_size:
            raise ValueError('A local H3 input changed after the capsule was frozen')
    return copy.deepcopy(recipe), source, references
