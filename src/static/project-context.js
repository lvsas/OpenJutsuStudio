/* Navigation context only: never a project registry, import or generation request. */
const keys = ['project_id', 'job_id', 'character_id'];
export const validContextId = value => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
export function parseProjectContext(search = '') {
  const params = new URLSearchParams(search), result = {};
  for (const key of keys) {
    const values = params.getAll(key);
    if (values.length > 1 || (values.length === 1 && !validContextId(values[0])))
      throw new Error('This workspace link is invalid. Open a workspace from the navigation to start safely.');
    result[key] = values[0] ?? null;
  }
  return result;
}
export function workspaceLink(path, values = {}, search = '') {
  if (!['/', '/h3', '/characters', '/timeline'].includes(path))
    throw new Error('Invalid workspace destination.');
  const {project_id} = parseProjectContext(search), params = new URLSearchParams();
  if (project_id) params.set('project_id', project_id);
  for (const [key, value] of Object.entries(values)) {
    if (!keys.includes(key) || !validContextId(value))
      throw new Error('This workspace link is invalid.');
    params.set(key, value);
  }
  return path + (params.size ? '?' + params : '');
}
