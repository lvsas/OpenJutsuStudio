"""Revisioned organization of projects; never delete source media or lineage."""
from timeline_models import ProjectAssets, MAX_KNOWN_CLIPS

GROUP = {'character': 'characters', 'job': 'jobs', 'take': 'takes'}


def exclusions(project):
    return ProjectAssets.model_validate(project.get('excluded_assets', {})).model_dump()


def clear_exclusion(project, group, asset_id):
    if 'excluded_assets' in project:
        hidden = exclusions(project)
        hidden[group] = [value for value in hidden[group] if value != asset_id]
        project['excluded_assets'] = hidden


def filtered_memberships(project, assets):
    hidden = exclusions(project)
    return {group: [value for value in values if value not in hidden[group]]
            for group, values in assets.items()}


def _aliases(store, assets, kind, asset_id):
    """A registered Swap and its native view describe the same chosen resource."""
    from continuable_take import get_take
    from timeline_swap_sources import native_take_link
    targets = {group: set() for group in GROUP.values()}
    targets[GROUP[kind]].add(asset_id)
    if kind == 'job':
        for take_id in assets['takes']:
            try:
                if get_take(store.work, take_id).to_manifest()['origin']['source_job'] == asset_id:
                    targets['takes'].add(take_id)
            except (ValueError, OSError, KeyError):
                pass
        try:
            link = native_take_link(store, store._job(asset_id)).get('native_take_id')
            if link:
                targets['takes'].add(link)
        except (ValueError, OSError):
            pass
    elif kind == 'take':
        try:
            origin_job = get_take(store.work, asset_id).to_manifest()['origin']['source_job']
        except (ValueError, OSError, KeyError):
            origin_job = None
        for job_id in assets['jobs']:
            try:
                if job_id == origin_job or native_take_link(store, store._job(job_id)).get('native_take_id') == asset_id:
                    targets['jobs'].add(job_id)
            except (ValueError, OSError):
                pass
    return targets


def dissociate_asset(store, project_id, data):
    from timeline_store import TimelineError, check_revision
    with store.lock:
        project = store._project(project_id)
        check_revision(data.revision, project['revision'])
        assets = store._memberships(project)
        targets = _aliases(store, assets, data.kind, data.asset_id)
        for placement in project.get('native_workspace', {}).get('placements', []):
            group = 'jobs' if placement.get('source_kind', 'native') == 'swap' else 'takes'
            if placement['take_id'] in targets[group]:
                raise TimelineError(409, 'Remove this resource from the sequence first. Its files will stay in the common library.')
        for placement in project.get('clips', []):
            known = project.get('known_clips', {}).get(placement['clip_id'], {})
            if known.get('source_job_id') in targets['jobs'] or known.get('take_id') in targets['takes']:
                raise TimelineError(409, 'This resource is still used in a saved cut. Remove its placement first.')
        hidden = exclusions(project)
        for group, ids in targets.items():
            hidden[group] = list(dict.fromkeys(hidden[group] + sorted(ids)))
            if len(hidden[group]) > MAX_KNOWN_CLIPS:
                raise TimelineError(422, 'This project resource list is full')
            assets[group] = [value for value in assets[group] if value not in ids]
        if project.get('character_id') in targets['characters']:
            project['character_id'] = None
        project['assets'], project['excluded_assets'] = assets, hidden
        store._save_edit(project, native=True)
        return store.get_assets(project_id)


def set_archived(store, project_id, revision, archived):
    from timeline_store import TimelineError, check_revision
    with store.lock:
        project = store._project(project_id)
        check_revision(revision, project['revision'])
        if archived and project.get('is_draft'):
            raise TimelineError(422, 'Save and name the Draft before archiving it.')
        if project.get('archived', False) != archived:
            project['archived'] = archived
            store._save_edit(project, native=True, allow_archived=True)
        return store.get(project_id)
